"""Pipeline orchestrator — top-level weekly-run flow.

Implements the step-by-step pipeline from Technical Sketch §6.
Each public function is a pure stage: f(inputs, config) → outputs.
"""

from __future__ import annotations

import math
from typing import Any

from .data.models import (
    Exclusion,
    Job,
    ReviewFlag,
    RouteResult,
    ScheduleAssignment,
    Technician,
    Vehicle,
    WeeklyException,
)
from .rules.scoring import ScoredJob, score_jobs
from .rules.slot_selection import find_best_eligible_slot, first_failing_rule
from .rules.helpers import find_helper
from .rules.workload import check_workload
from .routing.nearest_neighbour import build_route
from .postprocess.standby import select_standby_per_route
from .postprocess.readiness import compute_area_readiness
from .postprocess.flags import generate_review_flags


# ── Geo helper ──────────────────────────────────────────────────────────────

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ── Stage 2: Exclusion Filters ──────────────────────────────────────────────


def apply_exclusion_filters(
    jobs: list[Job],
) -> tuple[list[Job], list[Exclusion]]:
    """Partition jobs into candidates and exclusions based on status.

    Returns (candidates, exclusions).
    """
    candidates: list[Job] = []
    exclusions: list[Exclusion] = []

    for j in jobs:
        if j.status == "assigned":
            exclusions.append(Exclusion(
                job_id=j.job_id,
                reason_code="ALREADY_ASSIGNED",
                detail=f"Job status is '{j.status}'",
            ))
        elif j.status in {"excluded", "cancelled"}:
            exclusions.append(Exclusion(
                job_id=j.job_id,
                reason_code="STATUS_EXCLUDED",
                detail=f"Job status is '{j.status}'",
            ))
        else:
            candidates.append(j)

    return candidates, exclusions


# ── Stage 3: Apply Weekly Exceptions ────────────────────────────────────────


def apply_exceptions(
    technicians: list[Technician],
    vehicles: list[Vehicle],
    exceptions: list[WeeklyException],
) -> None:
    """Mutate technician/vehicle available_days in-place based on exceptions.

    • ``unavailable`` → remove the day entirely.
    • ``partial`` → day stays in the list (capacity handled downstream);
      the effect_value is preserved on the exception for later consumption.
    """
    tech_lookup = {t.tech_id: t for t in technicians}
    veh_lookup = {v.vehicle_id: v for v in vehicles}

    for ex in exceptions:
        if ex.scope_type == "technician":
            tech = tech_lookup.get(ex.scope_id)
            if tech is None:
                continue
            if ex.effect_type == "unavailable":
                tech.available_days = [
                    d for d in tech.available_days if d != ex.day
                ]
            # "partial" — keep the day; downstream stages read the exception
            # to reduce capacity / time budget for that (tech, day).

        elif ex.scope_type == "vehicle":
            veh = veh_lookup.get(ex.scope_id)
            if veh is None:
                continue
            if ex.effect_type == "unavailable":
                veh.available_days = [
                    d for d in veh.available_days if d != ex.day
                ]


# ── Stage 4: Reserve Special Routes ─────────────────────────────────────────

# Route types that are handled before the normal score-and-assign Phase 1.
_SPECIAL_ROUTE_TYPES = {"radiator", "nh_overnight", "helper"}


def split_special_routes(
    candidates: list[Job],
) -> tuple[list[Job], list[Job]]:
    """Partition candidates into (special_jobs, normal_jobs).

    A job is "special" if its route_type is radiator / nh_overnight / helper,
    or if helper_needed is True.
    """
    special: list[Job] = []
    normal: list[Job] = []
    for j in candidates:
        if j.route_type in _SPECIAL_ROUTE_TYPES or j.helper_needed:
            special.append(j)
        else:
            normal.append(j)
    return special, normal


def _skill_match(tech: Technician, job: Job) -> bool:
    """True when the technician's skill set covers the job's route_type needs.

    Mapping from route_type → required skill(s):
      • radiator  → {"radiator"}
      • nh_overnight → {"overhaul"}
      • helper    → {"install"}          (boiler install assist)
      • normal    → {"boiler_service"}   (fallback)
    """
    needs: set[str]
    if job.route_type == "radiator":
        needs = {"radiator"}
    elif job.route_type == "nh_overnight":
        needs = {"overhaul"}
    elif job.route_type == "helper" or job.helper_needed:
        needs = {"install"}
    else:
        needs = {"boiler_service"}
    return needs.issubset(set(tech.skills))


def _vehicle_capable(vehicle: Vehicle, job: Job) -> bool:
    """True when the vehicle's capability tags cover the job's route_type."""
    needs: set[str]
    if job.route_type == "radiator":
        needs = {"radiator"}
    elif job.route_type == "nh_overnight":
        needs = {"overhaul"}
    elif job.route_type == "helper" or job.helper_needed:
        needs = {"install"}
    else:
        needs = {"boiler_service"}
    return needs.issubset(set(vehicle.capability_tags))


def plan_special_routes(
    special_jobs: list[Job],
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
) -> tuple[list[ScheduleAssignment], list[Exclusion]]:
    """Assign special jobs to reserved (tech, vehicle, day) slots.

    Returns (assignments, exclusions).

    Uses a greedy approach: for each special job, find the first eligible
    (tech, vehicle, day) triple that satisfies skill match, vehicle capability,
    availability, cluster radius, and capacity — then reserve it.

    Helper jobs additionally require a second eligible technician.
    """
    R = config.get("R_cluster_radius_m", 30_000)
    T_max = config.get("T_max_minutes", 480)
    phase1_frac = config.get("T_max_phase1_fraction", 0.80)
    time_budget = T_max * phase1_frac

    # Mutable capacity trackers
    # (vehicle_id, day) → number of stops already assigned
    stop_count: dict[tuple[str, str], int] = {}
    # (tech_id, day) → total service minutes already committed
    service_mins: dict[tuple[str, str], float] = {}
    # (tech_id, day) → vehicle_id already paired on that day
    tech_veh: dict[tuple[str, str], str] = {}
    # (vehicle_id, day) → tech_id already driving on that day
    veh_tech: dict[tuple[str, str], str] = {}

    assignments: list[ScheduleAssignment] = []
    exclusions: list[Exclusion] = []

    # Process special jobs sorted by age (oldest first) then value (highest first)
    # to give priority to the most urgent / valuable special work.
    sorted_specials = sorted(
        special_jobs, key=lambda j: (-j.age_days, -j.value)
    )

    for job in sorted_specials:
        best = _find_special_slot(
            job, technicians, vehicles, config,
            R, time_budget, stop_count, service_mins, tech_veh, veh_tech,
        )

        if best is None:
            exclusions.append(Exclusion(
                job_id=job.job_id,
                reason_code="NO_ELIGIBLE_TRIPLE",
                detail=(
                    f"No eligible (tech, vehicle, day) for "
                    f"route_type={job.route_type!r}"
                ),
            ))
            continue

        tech_id, veh_id, day = best

        # Find helper for two-man jobs
        helper_id: str | None = None
        if job.helper_needed:
            helper_id = _find_helper_tech(
                job, day, tech_id, technicians, R
            )
            if helper_id is None:
                exclusions.append(Exclusion(
                    job_id=job.job_id,
                    reason_code="HELPER_UNAVAIL",
                    detail="No second technician available for helper job",
                ))
                continue

        # Commit assignment
        assignments.append(ScheduleAssignment(
            job_id=job.job_id,
            tech_id=tech_id,
            vehicle_id=veh_id,
            day=day,
            helper_tech_id=helper_id,
        ))
        _commit_slot(
            tech_id, veh_id, day, job,
            stop_count, service_mins, tech_veh, veh_tech,
        )

    return assignments, exclusions


def _find_special_slot(
    job: Job,
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
    R: float,
    time_budget: float,
    stop_count: dict[tuple[str, str], int],
    service_mins: dict[tuple[str, str], float],
    tech_veh: dict[tuple[str, str], str],
    veh_tech: dict[tuple[str, str], str],
) -> tuple[str, str, str] | None:
    """Find the best eligible (tech_id, vehicle_id, day) for *job*.

    Selection priority: closest depot → lightest day → cheapest vehicle.
    Returns None if nothing is feasible.
    """
    P_max = config.get("P_max_stops", 14)
    candidates: list[tuple[float, int, float, str, str, str]] = []

    for tech in technicians:
        if not _skill_match(tech, job):
            continue
        dist = _haversine_m(tech.home_lat, tech.home_lon,
                            job.latitude, job.longitude)
        if dist > R:
            continue

        for veh in vehicles:
            if not _vehicle_capable(veh, job):
                continue
            for day in tech.available_days:
                if day not in veh.available_days:
                    continue
                # ONE_VEH_PER_TECH
                existing_veh = tech_veh.get((tech.tech_id, day))
                if existing_veh is not None and existing_veh != veh.vehicle_id:
                    continue
                # ONE_TECH_PER_VEH
                existing_tech = veh_tech.get((veh.vehicle_id, day))
                if existing_tech is not None and existing_tech != tech.tech_id:
                    continue
                # CAPACITY_OK
                if stop_count.get((veh.vehicle_id, day), 0) >= min(veh.capacity, P_max):
                    continue
                # TIME_OK
                if (service_mins.get((tech.tech_id, day), 0.0)
                        + job.service_time_min > time_budget):
                    continue

                # Rank: closest depot, lightest day, cheapest vehicle
                day_load = stop_count.get((veh.vehicle_id, day), 0)
                candidates.append(
                    (dist, day_load, veh.cost_per_metre,
                     tech.tech_id, veh.vehicle_id, day)
                )

    if not candidates:
        return None
    candidates.sort()
    best = candidates[0]
    return best[3], best[4], best[5]


def _find_helper_tech(
    job: Job,
    day: str,
    primary_tech_id: str,
    technicians: list[Technician],
    R: float,
) -> str | None:
    """Find a second technician to assist on *day* for a helper job.

    Must be available on the day, have matching skills, and be within radius.
    Returns the helper tech_id or None.
    """
    best: tuple[float, str] | None = None
    for tech in technicians:
        if tech.tech_id == primary_tech_id:
            continue
        if day not in tech.available_days:
            continue
        if not _skill_match(tech, job):
            continue
        dist = _haversine_m(tech.home_lat, tech.home_lon,
                            job.latitude, job.longitude)
        if dist > R:
            continue
        if best is None or dist < best[0]:
            best = (dist, tech.tech_id)
    return best[1] if best else None


def _commit_slot(
    tech_id: str,
    veh_id: str,
    day: str,
    job: Job,
    stop_count: dict[tuple[str, str], int],
    service_mins: dict[tuple[str, str], float],
    tech_veh: dict[tuple[str, str], str],
    veh_tech: dict[tuple[str, str], str],
) -> None:
    """Record that *job* has been assigned to (tech, vehicle, day)."""
    stop_count[(veh_id, day)] = stop_count.get((veh_id, day), 0) + 1
    service_mins[(tech_id, day)] = (
        service_mins.get((tech_id, day), 0.0) + job.service_time_min
    )
    tech_veh[(tech_id, day)] = veh_id
    veh_tech[(veh_id, day)] = tech_id


def compute_consumed_capacity(
    assignments: list[ScheduleAssignment],
    jobs_lookup: dict[str, Job],
) -> dict[str, Any]:
    """Summarise capacity consumed by special-route assignments.

    Returns a dict with:
      "stop_count"   : {(vehicle_id, day): int}
      "service_mins" : {(tech_id, day): float}
      "tech_veh"     : {(tech_id, day): vehicle_id}
      "veh_tech"     : {(vehicle_id, day): tech_id}
    """
    stop_count: dict[tuple[str, str], int] = {}
    service_mins: dict[tuple[str, str], float] = {}
    tech_veh: dict[tuple[str, str], str] = {}
    veh_tech: dict[tuple[str, str], str] = {}

    for a in assignments:
        job = jobs_lookup[a.job_id]
        _commit_slot(
            a.tech_id, a.vehicle_id, a.day, job,
            stop_count, service_mins, tech_veh, veh_tech,
        )

    return {
        "stop_count": stop_count,
        "service_mins": service_mins,
        "tech_veh": tech_veh,
        "veh_tech": veh_tech,
    }


# ── Stage 5: Phase 1 — Score & Schedule ─────────────────────────────────────


def run_phase1_schedule(
    normal_jobs: list[Job],
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
    consumed_capacity: dict[str, Any],
    area_assigned_counts: dict[str, int] | None = None,
    prohibited_pairs: set[tuple[str, str]] | None = None,
) -> tuple[list[ScheduleAssignment], list[Exclusion], list[ReviewFlag]]:
    """Phase 1 rules-based score-and-assign scheduling.

    1. Score all normal jobs.
    2. Sort by (-score, -age_days, -value).
    3. Greedy assign: for each job find the best eligible slot.
    4. Helper pass: for helper-needed jobs, find a second tech.
    5. Workload review: generate TECH_OVERLOAD / VEH_BOTTLENECK flags.

    Returns (assignments, exclusions, workload_flags).
    """
    if prohibited_pairs is None:
        prohibited_pairs = set()

    # Unpack mutable capacity state (seeded from special-route assignments)
    stop_count: dict[tuple[str, str], int] = dict(
        consumed_capacity.get("stop_count", {})
    )
    service_mins: dict[tuple[str, str], float] = dict(
        consumed_capacity.get("service_mins", {})
    )
    tech_veh: dict[tuple[str, str], str] = dict(
        consumed_capacity.get("tech_veh", {})
    )
    veh_tech: dict[tuple[str, str], str] = dict(
        consumed_capacity.get("veh_tech", {})
    )

    # ── 1. Score ────────────────────────────────────────────────────
    scored = score_jobs(
        normal_jobs, technicians, config, area_assigned_counts
    )

    # ── 2. Sort ─────────────────────────────────────────────────────
    scored.sort(key=lambda s: (-s.score, -s.job.age_days, -s.job.value))

    # ── 3 & 4. Greedy assign + helper pass ──────────────────────────
    assignments: list[ScheduleAssignment] = []
    exclusions: list[Exclusion] = []

    for sj in scored:
        job = sj.job
        best = find_best_eligible_slot(
            job, technicians, vehicles, config,
            stop_count, service_mins, tech_veh, veh_tech,
            prohibited_pairs,
        )

        if best is None:
            reason = first_failing_rule(
                job, technicians, vehicles, config,
                stop_count, service_mins, tech_veh, veh_tech,
                prohibited_pairs,
            )
            exclusions.append(Exclusion(
                job_id=job.job_id,
                reason_code=reason,
                detail=f"No eligible slot for job {job.job_id}",
            ))
            continue

        tech_id, veh_id, day = best

        # Helper pass for two-man jobs
        helper_id: str | None = None
        if job.helper_needed:
            helper_id = find_helper(
                job, day, tech_id, technicians, config,
                service_mins, prohibited_pairs,
            )
            if helper_id is None:
                exclusions.append(Exclusion(
                    job_id=job.job_id,
                    reason_code="HELPER_UNAVAIL",
                    detail=f"No helper tech available for job {job.job_id} on {day}",
                ))
                continue

        # Commit the assignment
        assignments.append(ScheduleAssignment(
            job_id=job.job_id,
            tech_id=tech_id,
            vehicle_id=veh_id,
            day=day,
            helper_tech_id=helper_id,
        ))
        _commit_slot(
            tech_id, veh_id, day, job,
            stop_count, service_mins, tech_veh, veh_tech,
        )

    # ── 5. Workload review ──────────────────────────────────────────
    jobs_service_mins = {j.job_id: j.service_time_min for j in normal_jobs}
    workload_flags = check_workload(
        assignments, jobs_service_mins, technicians, vehicles, config,
    )

    return assignments, exclusions, workload_flags


# ── Stage 6: Phase 2 — Order Stops ──────────────────────────────────────────


def run_phase2_routing(
    assignments: list[ScheduleAssignment],
    technicians: list[Technician],
    vehicles: list[Vehicle],
    jobs_lookup: dict[str, Job],
    config: dict[str, Any],
) -> tuple[list[RouteResult], list[Exclusion], list[ReviewFlag]]:
    """Phase 2 nearest-neighbour routing for every (tech, vehicle, day) bundle.

    1. Group Phase 1 assignments by (tech_id, vehicle_id, day).
    2. For each group, build an NN route with feasibility verification.
    3. Collect ROUTE_DROP exclusions and CROSS_AREA / NO_FEASIBLE flags.

    Returns (routes, exclusions, review_flags).
    """
    tech_map = {t.tech_id: t for t in technicians}
    veh_map = {v.vehicle_id: v for v in vehicles}

    # Group assignments by (tech, vehicle, day)
    bundles: dict[tuple[str, str, str], list[Job]] = {}
    for a in assignments:
        key = (a.tech_id, a.vehicle_id, a.day)
        job = jobs_lookup.get(a.job_id)
        if job is not None:
            bundles.setdefault(key, []).append(job)

    routes: list[RouteResult] = []
    exclusions: list[Exclusion] = []
    flags: list[ReviewFlag] = []

    for (tech_id, veh_id, day), bundle_jobs in sorted(bundles.items()):
        tech = tech_map[tech_id]
        veh = veh_map[veh_id]

        route, dropped_ids, route_flags = build_route(
            tech, veh, day, bundle_jobs, config,
        )

        routes.append(route)
        flags.extend(route_flags)

        for jid in dropped_ids:
            exclusions.append(Exclusion(
                job_id=jid,
                reason_code="ROUTE_DROP",
                detail=(
                    f"Phase-1-scheduled job dropped during Phase 2 routing "
                    f"for {tech_id}/{veh_id}/{day}"
                ),
            ))

    return routes, exclusions, flags


# ── Stage 7: Post-processing ────────────────────────────────────────────────


def run_postprocessing(
    routes: list[RouteResult],
    candidate_jobs: list[Job],
    assignments: list[ScheduleAssignment],
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
) -> tuple[
    dict[tuple[str, str, str], list[str]],   # standby
    dict[str, str],                           # readiness
    list[ReviewFlag],                         # flags
]:
    """Post-processing: standby ranking, area readiness, review flags.

    Returns (standby, readiness, flags).
    """
    # Determine unassigned candidates
    visited_ids: set[str] = set()
    for r in routes:
        visited_ids.update(r.visited_job_ids)
    unassigned = [j for j in candidate_jobs if j.job_id not in visited_ids]

    # Standby ranking per route
    standby = select_standby_per_route(
        routes, unassigned, technicians, vehicles, config,
    )

    # Area readiness
    readiness = compute_area_readiness(
        routes, standby, candidate_jobs, config,
    )

    # Review flags (DUP_ADDR, WEAK_STANDBY, HELPER_TRAVEL, GEOCODE_OOB)
    flags = generate_review_flags(
        candidate_jobs, assignments, technicians, standby, config,
    )

    return standby, readiness, flags
