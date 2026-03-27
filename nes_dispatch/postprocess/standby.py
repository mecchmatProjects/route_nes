"""Standby job ranking (Technical Sketch §7, Stage 7).

For each route, rank unassigned jobs that *could* substitute for a
visited stop if one cancels.  Standby candidates must be in the same
area as the route's visited jobs, within cluster radius, and have
compatible skill/capability requirements met by the route's tech/vehicle.

Jobs are ranked by composite score (geo proximity to route centroid,
then age, then value) so the dispatcher knows which backup to pull first.
"""

from __future__ import annotations

import math
from typing import Any

from ..data.models import Job, RouteResult, Technician, Vehicle
from ..routing.distance import haversine_m


def _route_centroid(
    jobs: list[Job],
) -> tuple[float, float]:
    """Average lat/lon of the jobs on a route."""
    if not jobs:
        return 0.0, 0.0
    lat = sum(j.latitude for j in jobs) / len(jobs)
    lon = sum(j.longitude for j in jobs) / len(jobs)
    return lat, lon


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
    """Rank standby candidates for each route.

    Returns {(tech_id, vehicle_id, day): [job_id, ...]}
    ordered best-first.
    """
    R = config.get("R_cluster_radius_m", 30_000)
    tech_map = {t.tech_id: t for t in technicians}
    veh_map = {v.vehicle_id: v for v in vehicles}
    jobs_map = {j.job_id: j for j in unassigned_jobs}

    result: dict[tuple[str, str, str], list[str]] = {}

    for route in routes:
        if not route.visited_job_ids:
            key = (route.tech_id, route.vehicle_id, route.day)
            result[key] = []
            continue

        tech = tech_map.get(route.tech_id)
        veh = veh_map.get(route.vehicle_id)
        if tech is None or veh is None:
            continue

        # Collect areas covered by this route
        route_jobs = [jobs_map[jid] for jid in route.visited_job_ids
                      if jid in jobs_map]
        # If visited jobs aren't in unassigned, we need the full jobs list —
        # but visited_job_ids may not be in unassigned.  Use centroid anyway.
        centroid_lat, centroid_lon = tech.home_lat, tech.home_lon
        if route_jobs:
            centroid_lat, centroid_lon = _route_centroid(route_jobs)

        route_areas = set()
        for jid in route.visited_job_ids:
            j = jobs_map.get(jid)
            if j:
                route_areas.add(j.area_id)

        # Score each unassigned job as a standby candidate
        scored: list[tuple[float, str]] = []
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

            # Proximity to route centroid (lower = better)
            centroid_dist = haversine_m(
                centroid_lat, centroid_lon,
                job.latitude, job.longitude,
            )

            # Composite rank key: proximity, then -age, then -value
            scored.append((centroid_dist, -job.age_days, -job.value, job.job_id))

        scored.sort()
        key = (route.tech_id, route.vehicle_id, route.day)
        result[key] = [jid for (_, _, _, jid) in scored]

    return result
