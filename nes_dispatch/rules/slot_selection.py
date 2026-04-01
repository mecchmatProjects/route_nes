"""Best-fit slot selection (Technical Sketch §5, Stage 5.3).

Given a job, iterate all (tech, vehicle, day) combinations, apply
eligibility rules, and return the best-fit slot ranked by:
    1. closest depot  (lowest haversine distance)
    2. lightest day   (fewest stops already assigned)
    3. cheapest vehicle (lowest cost_per_metre)
"""

from __future__ import annotations

import math
from typing import Any

from ..data.models import Job, ScheduleAssignment, Technician, Vehicle
from .eligibility import check_eligibility, _haversine_m


def find_best_eligible_slot(
    job: Job,
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
    stop_count: dict[tuple[str, str], int],
    service_mins: dict[tuple[str, str], float],
    tech_veh: dict[tuple[str, str], str],
    veh_tech: dict[tuple[str, str], str],
    prohibited_pairs: set[tuple[str, str]] | None = None,
) -> tuple[str, str, str] | None:
    """Return the best eligible (tech_id, vehicle_id, day) for *job*, or None.

    Also returns None when every candidate slot fails at least one rule.
    """
    if prohibited_pairs is None:
        prohibited_pairs = set()

    # Collect all eligible slots with their ranking keys
    candidates: list[tuple[float, int, float, str, str, str]] = []

    for tech in technicians:
        dist = _haversine_m(tech.home_lat, tech.home_lon,
                            job.latitude, job.longitude)
        for vehicle in vehicles:
            for day in tech.available_days:
                failures = check_eligibility(
                    job, tech, vehicle, day, config,
                    stop_count, service_mins, tech_veh, veh_tech,
                    prohibited_pairs,
                )
                if failures:
                    continue

                day_load = stop_count.get((vehicle.vehicle_id, day), 0)
                candidates.append((
                    dist,
                    day_load,
                    vehicle.cost_per_metre,
                    tech.tech_id,
                    vehicle.vehicle_id,
                    day,
                ))

    if not candidates:
        return None
    candidates.sort()
    best = candidates[0]
    return best[3], best[4], best[5]


def first_failing_rule(
    job: Job,
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
    stop_count: dict[tuple[str, str], int],
    service_mins: dict[tuple[str, str], float],
    tech_veh: dict[tuple[str, str], str],
    veh_tech: dict[tuple[str, str], str],
    prohibited_pairs: set[tuple[str, str]] | None = None,
) -> str:
    """Return the most-common failing rule across all slots for *job*.

    Used to produce an informative exclusion reason code.
    """
    if prohibited_pairs is None:
        prohibited_pairs = set()

    rule_counts: dict[str, int] = {}
    for tech in technicians:
        for vehicle in vehicles:
            for day in tech.available_days:
                failures = check_eligibility(
                    job, tech, vehicle, day, config,
                    stop_count, service_mins, tech_veh, veh_tech,
                    prohibited_pairs,
                )
                for f in failures:
                    rule_counts[f] = rule_counts.get(f, 0) + 1

    if not rule_counts:
        return "NO_ELIGIBLE_TRIPLE"

    # Map rule names to exclusion reason codes
    _RULE_TO_REASON = {
        "SKILL_MATCH": "SKILL_MISMATCH",
        "VEH_CAPABILITY": "VEHICLE_MISMATCH",
        "VEH_WORK_ELIGIBLE": "V4_CATEGORY_BLOCKED",
        "WITHIN_RADIUS": "CLUSTER_RADIUS",
        "CAPACITY_OK": "CAPACITY_FULL",
        "BOOKED_CAP": "BOOKED_CAP_FULL",
        "TIME_OK": "TIME_BUDGET",
        "NOT_PROHIBITED": "PROHIBITED_PAIR",
    }
    # Return the most frequent failing rule, mapped to an exclusion code
    dominant = max(rule_counts, key=rule_counts.get)  # type: ignore[arg-type]
    return _RULE_TO_REASON.get(dominant, "NO_ELIGIBLE_TRIPLE")
