"""Standby job selection (spec §7).

Spec: "For standard routes, the two standby jobs should be the
lowest-priority jobs among otherwise acceptable route candidates."

Standby candidates are scored with the same decision-ladder as Phase 1,
then the *lowest*-scoring acceptable candidates are chosen — they are
the jobs most easily bumped if a higher-priority job needs the slot.
"""

from __future__ import annotations

from typing import Any

from ..data.models import Job, RouteResult, Technician, Vehicle
from ..routing.distance import haversine_m
from ..rules.scoring import score_jobs


def _basic_skill_check(tech: Technician, job: Job) -> bool:
    """Simplified skill compatibility (same logic as eligibility)."""
    if job.route_type == "radiator":
        needs = {"radiator"}
    elif job.route_type == "nh_overnight":
        needs = {"overhaul"}
    elif job.route_type == "helper" or job.helper_needed:
        needs = {"install"}
    else:
        needs = {"boiler_service"}
    return needs.issubset(set(tech.skills))


def _basic_veh_check(vehicle: Vehicle, job: Job) -> bool:
    """Simplified vehicle capability check."""
    if job.route_type == "radiator":
        needs = {"radiator"}
    elif job.route_type == "nh_overnight":
        needs = {"overhaul"}
    elif job.route_type == "helper" or job.helper_needed:
        needs = {"install"}
    else:
        needs = {"boiler_service"}
    return needs.issubset(set(vehicle.capability_tags))


def select_standby_per_route(
    routes: list[RouteResult],
    unassigned_jobs: list[Job],
    technicians: list[Technician],
    vehicles: list[Vehicle],
    config: dict[str, Any],
) -> dict[tuple[str, str, str], list[str]]:
    """Select standby candidates for each route.

    Spec §7: standby = lowest-priority acceptable candidates.
    Uses the same decision-ladder scoring as Phase 1, picks the bottom N.

    Returns {(tech_id, vehicle_id, day): [job_id, ...]}
    ordered lowest-priority-first.
    """
    R = config.get("R_cluster_radius_m", 30_000)
    n_standby = config.get("n_standby", 2)  # spec §5: 2 standby per route
    tech_map = {t.tech_id: t for t in technicians}
    veh_map = {v.vehicle_id: v for v in vehicles}

    # Pre-score all unassigned jobs using the decision ladder
    if unassigned_jobs:
        scored_all = score_jobs(unassigned_jobs, technicians, config)
        score_by_id = {sj.job.job_id: sj.score for sj in scored_all}
    else:
        score_by_id = {}

    result: dict[tuple[str, str, str], list[str]] = {}

    for route in routes:
        key = (route.tech_id, route.vehicle_id, route.day)
        if not route.visited_job_ids:
            result[key] = []
            continue

        tech = tech_map.get(route.tech_id)
        veh = veh_map.get(route.vehicle_id)
        if tech is None or veh is None:
            result[key] = []
            continue

        # Filter to acceptable candidates for this route's tech/vehicle
        acceptable: list[tuple[float, str]] = []
        for job in unassigned_jobs:
            # Must be within cluster radius of tech depot
            depot_dist = haversine_m(
                tech.home_lat, tech.home_lon,
                job.latitude, job.longitude,
            )
            if depot_dist > R:
                continue

            # Skill / capability compatibility
            if not _basic_skill_check(tech, job):
                continue
            if not _basic_veh_check(veh, job):
                continue

            # Score from decision ladder (lower = lower-priority = standby)
            score = score_by_id.get(job.job_id, 0.0)
            acceptable.append((score, job.job_id))

        # Sort ascending: lowest-priority first → those become standby
        acceptable.sort()
        result[key] = [jid for (_, jid) in acceptable[:n_standby]]

    return result
