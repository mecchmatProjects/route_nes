"""Workload-review flags (Technical Sketch §5, Stage 5.5).

Post-assignment review — generates ReviewFlag items without
moving any jobs.  Two flag types:

  • TECH_OVERLOAD  — tech's weekly committed minutes exceed the
    overload threshold (default 90 % of total weekly capacity).
  • VEH_BOTTLENECK — a vehicle is at capacity on ≥ N days
    (default 4 days).
"""

from __future__ import annotations

from typing import Any

from ..data.models import ReviewFlag, ScheduleAssignment, Technician, Vehicle


def check_workload(
    assignments: list[ScheduleAssignment],
    jobs_service_mins: dict[str, float],
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
) -> list[ReviewFlag]:
    """Generate workload-review flags for the current schedule.

    Parameters
    ----------
    assignments:
        All ScheduleAssignment produced so far (special + Phase 1).
    jobs_service_mins:
        Mapping {job_id: service_time_min} for quick lookup.
    technicians:
        Full technician list.
    vehicles:
        Full vehicle list.
    config:
        Must contain: T_max_minutes, T_max_phase1_fraction,
        tech_overload_pct, veh_bottleneck_days, P_max_stops.

    Returns a (possibly empty) list of ReviewFlag.
    """
    T_max = config.get("T_max_minutes", 480)
    phase1_frac = config.get("T_max_phase1_fraction", 0.80)
    budget_per_day = T_max * phase1_frac
    overload_pct = config.get("tech_overload_pct", 0.90)
    bottleneck_days = config.get("veh_bottleneck_days", 4)
    P_max = config.get("P_max_stops", 14)

    flags: list[ReviewFlag] = []

    # ── TECH_OVERLOAD ───────────────────────────────────────────────
    # Aggregate committed minutes per technician across the week.
    tech_days: dict[str, set[str]] = {}
    tech_mins: dict[str, float] = {}
    for a in assignments:
        mins = jobs_service_mins.get(a.job_id, 0.0)
        tech_mins[a.tech_id] = tech_mins.get(a.tech_id, 0.0) + mins
        tech_days.setdefault(a.tech_id, set()).add(a.day)
        # helper_required is a boolean flag; no named helper to track

    tech_lookup = {t.tech_id: t for t in technicians}
    for tech_id, total_mins in tech_mins.items():
        tech = tech_lookup.get(tech_id)
        if tech is None:
            continue
        working_days = len(tech.available_days)
        weekly_capacity = budget_per_day * working_days
        if weekly_capacity <= 0:
            continue
        utilisation = total_mins / weekly_capacity
        if utilisation > overload_pct:
            flags.append(ReviewFlag(
                code="TECH_OVERLOAD",
                severity="WARN",
                message=(
                    f"Tech {tech_id} is at {utilisation:.0%} weekly "
                    f"utilisation (threshold {overload_pct:.0%})."
                ),
                refs={"tech_id": tech_id, "utilisation": round(utilisation, 3)},
            ))

    # ── VEH_BOTTLENECK ──────────────────────────────────────────────
    # Count how many days each vehicle is at full capacity.
    veh_day_stops: dict[tuple[str, str], int] = {}
    for a in assignments:
        key = (a.vehicle_id, a.day)
        veh_day_stops[key] = veh_day_stops.get(key, 0) + 1

    veh_lookup = {v.vehicle_id: v for v in vehicles}
    veh_full_days: dict[str, int] = {}
    for (vid, day), stops in veh_day_stops.items():
        veh = veh_lookup.get(vid)
        if veh is None:
            continue
        cap = min(veh.capacity, P_max)
        if stops >= cap:
            veh_full_days[vid] = veh_full_days.get(vid, 0) + 1

    for vid, full_count in veh_full_days.items():
        if full_count >= bottleneck_days:
            flags.append(ReviewFlag(
                code="VEH_BOTTLENECK",
                severity="WARN",
                message=(
                    f"Vehicle {vid} is at capacity on {full_count} days "
                    f"(threshold {bottleneck_days})."
                ),
                refs={"vehicle_id": vid, "full_days": full_count},
            ))

    return flags
