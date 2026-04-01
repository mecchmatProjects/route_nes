"""Review-flag generation for post-processing (Technical Sketch §8).

Produces the five flag codes that are NOT already emitted by earlier
pipeline stages:

* DUP_ADDR              (INFO)     — ≥2 jobs sharing a street address
* MISSING_PLANNED_HOURS (WARN)     — job lacks required_job_hours; engine defaulted
* WEAK_STANDBY          (WARN)     — <threshold standby candidates for a route
* HELPER_REQUIRED       (INFO)     — route contains helper-required jobs
* GEOCODE_OOB           (CRITICAL) — job coordinates outside NE bounding box

The remaining five flags (CROSS_AREA, VEH_BOTTLENECK, TECH_OVERLOAD,
ROUTE_DROP, NO_FEASIBLE) are already generated upstream.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..data.models import (
    Job, ReviewFlag, ScheduleAssignment, Technician,
    REQUIRED_HOURS_CATEGORIES, RADIATOR_HOURS_CATEGORIES,
    ACCEPTED_QUOTE_CATEGORY,
)
from ..routing.distance import haversine_m


# ── Individual flag generators ──────────────────────────────────────────────


def flag_dup_addr(candidate_jobs: list[Job]) -> list[ReviewFlag]:
    """Flag addresses shared by ≥2 candidate jobs."""
    addr_counts: Counter[str] = Counter()
    addr_jobs: dict[str, list[str]] = {}
    for j in candidate_jobs:
        normalised = j.address.strip().lower()
        addr_counts[normalised] += 1
        addr_jobs.setdefault(normalised, []).append(j.job_id)

    flags: list[ReviewFlag] = []
    for addr, count in addr_counts.items():
        if count >= 2:
            flags.append(ReviewFlag(
                code="DUP_ADDR",
                severity="INFO",
                message=f"{count} jobs share address '{addr}'",
                refs={"address": addr, "job_ids": addr_jobs[addr]},
            ))
    return flags


def flag_weak_standby(
    standby: dict[tuple[str, str, str], list[str]],
    config: dict[str, Any],
) -> list[ReviewFlag]:
    """Flag routes with fewer than *weak_standby_threshold* standby candidates."""
    threshold = config.get("weak_standby_threshold", 2)
    flags: list[ReviewFlag] = []
    for key, candidates in standby.items():
        if len(candidates) < threshold:
            tech_id, veh_id, day = key
            flags.append(ReviewFlag(
                code="WEAK_STANDBY",
                severity="WARN",
                message=(
                    f"Route {tech_id}/{veh_id}/{day} has only "
                    f"{len(candidates)} standby candidate(s) "
                    f"(threshold={threshold})"
                ),
                refs={"tech_id": tech_id, "vehicle_id": veh_id,
                      "day": day, "count": len(candidates)},
            ))
    return flags


def flag_helper_travel(
    assignments: list[ScheduleAssignment],
    technicians: list[Technician],
    config: dict[str, Any],
) -> list[ReviewFlag]:
    """Flag route/day pairs that require a helper (spec §5: flag only)."""
    flags: list[ReviewFlag] = []

    for a in assignments:
        if not a.helper_required:
            continue
        flags.append(ReviewFlag(
            code="HELPER_REQUIRED",
            severity="INFO",
            message=(
                f"Job {a.job_id} on {a.day} ({a.tech_id}/{a.vehicle_id}) "
                f"requires a helper."
            ),
            refs={"job_id": a.job_id, "tech_id": a.tech_id,
                  "day": a.day},
        ))
    return flags


def flag_geocode_oob(
    candidate_jobs: list[Job],
    config: dict[str, Any],
) -> list[ReviewFlag]:
    """Flag jobs whose coordinates fall outside the NE bounding box."""
    lat_lo, lat_hi = config.get("lat_bounds", [41.0, 48.0])
    lon_lo, lon_hi = config.get("lon_bounds", [-74.0, -67.0])
    flags: list[ReviewFlag] = []
    for j in candidate_jobs:
        if not (lat_lo <= j.latitude <= lat_hi and
                lon_lo <= j.longitude <= lon_hi):
            flags.append(ReviewFlag(
                code="GEOCODE_OOB",
                severity="CRITICAL",
                message=(
                    f"Job {j.job_id} at ({j.latitude}, {j.longitude}) "
                    f"is outside bounding box "
                    f"[{lat_lo}–{lat_hi}] × [{lon_lo}–{lon_hi}]"
                ),
                refs={"job_id": j.job_id,
                      "lat": j.latitude, "lon": j.longitude},
            ))
    return flags


def flag_missing_planned_hours(
    candidate_jobs: list[Job],
) -> list[ReviewFlag]:
    """Flag jobs in Required-Hours categories that lack required_job_hours.

    Spec addendum §3: categories that use Required Job Hours for Scheduling
    expect the field to be present.  When missing, the engine falls back to
    1.0 h but surfaces a Pre-Route Communication warning for Ryan.
    """
    _needs_hours = (
        REQUIRED_HOURS_CATEGORIES
        | RADIATOR_HOURS_CATEGORIES
        | {ACCEPTED_QUOTE_CATEGORY}
    )
    flags: list[ReviewFlag] = []
    for j in candidate_jobs:
        if j.job_category in _needs_hours and not j.required_job_hours:
            # Accepted Quotes with total_job_amount can derive hours — skip
            if (j.job_category == ACCEPTED_QUOTE_CATEGORY
                    and j.total_job_amount and j.total_job_amount > 0):
                continue
            flags.append(ReviewFlag(
                code="MISSING_PLANNED_HOURS",
                severity="WARN",
                message=(
                    f"Job {j.job_id} (category '{j.job_category}') has no "
                    f"Required Job Hours; engine defaulted to 1.0 h."
                ),
                refs={"job_id": j.job_id,
                      "job_category": j.job_category},
            ))
    return flags


# ── Aggregate entry point ──────────────────────────────────────────────────


def generate_review_flags(
    candidate_jobs: list[Job],
    assignments: list[ScheduleAssignment],
    technicians: list[Technician],
    standby: dict[tuple[str, str, str], list[str]],
    config: dict[str, Any],
) -> list[ReviewFlag]:
    """Produce all post-processing review flags."""
    flags: list[ReviewFlag] = []
    flags.extend(flag_dup_addr(candidate_jobs))
    flags.extend(flag_missing_planned_hours(candidate_jobs))
    flags.extend(flag_weak_standby(standby, config))
    flags.extend(flag_helper_travel(assignments, technicians, config))
    flags.extend(flag_geocode_oob(candidate_jobs, config))
    return flags
