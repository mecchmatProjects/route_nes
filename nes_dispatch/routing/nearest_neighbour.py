"""Nearest-neighbour stop ordering + feasibility verification.

Technical Sketch §5, Stage 6 — Phase 2: Order Stops.

For each (tech, vehicle, day) bundle from Phase 1:
  1. NN sequencing: depot → closest unvisited → … → depot.
  2. Feasibility: walk the route and enforce T_max, Q_k, r inter-stop.
  3. Drop last-added job if T_max / Q_k violated; re-run NN on reduced set.
"""

from __future__ import annotations

from typing import Any

from ..data.models import Job, ReviewFlag, RouteResult, Technician, Vehicle
from .distance import haversine_m, travel_time_min


# ── Nearest-neighbour sequencing ────────────────────────────────────────────


def _nn_order(
    depot_lat: float,
    depot_lon: float,
    jobs: list[Job],
) -> list[Job]:
    """Return *jobs* ordered by greedy nearest-neighbour from *depot*.

    Start at (depot_lat, depot_lon), repeatedly visit the closest
    unvisited job, return to depot (the return leg is accounted for
    in feasibility, not in the ordering).
    """
    remaining = list(jobs)
    ordered: list[Job] = []
    cur_lat, cur_lon = depot_lat, depot_lon

    while remaining:
        best_idx = 0
        best_dist = haversine_m(cur_lat, cur_lon,
                                remaining[0].latitude, remaining[0].longitude)
        for i in range(1, len(remaining)):
            d = haversine_m(cur_lat, cur_lon,
                            remaining[i].latitude, remaining[i].longitude)
            if d < best_dist:
                best_dist = d
                best_idx = i

        chosen = remaining.pop(best_idx)
        ordered.append(chosen)
        cur_lat, cur_lon = chosen.latitude, chosen.longitude

    return ordered


# ── Feasibility verification ────────────────────────────────────────────────


def _walk_route(
    depot_lat: float,
    depot_lon: float,
    ordered_jobs: list[Job],
    speed_mpm: float,
    T_max: float,
    Q_max: int,
    r_interstop: float,
) -> tuple[list[Job], list[Job], float, float, list[str]]:
    """Walk *ordered_jobs* checking time, capacity, and inter-stop limits.

    Returns:
        (visited, dropped, total_distance_m, total_time_min, cross_area_jobs)

    Strategy: greedily add stops in NN order.  When adding stop i would
    violate T_max (travel+service+return) or Q_max, drop it and continue
    checking the rest from the *previous* position.
    """
    visited: list[Job] = []
    dropped: list[Job] = []
    cross_area_jobs: list[str] = []

    cur_lat, cur_lon = depot_lat, depot_lon
    total_dist = 0.0
    total_time = 0.0  # travel + service

    for job in ordered_jobs:
        # Distance from current position to this job
        leg_dist = haversine_m(cur_lat, cur_lon, job.latitude, job.longitude)
        leg_travel = travel_time_min(leg_dist, speed_mpm)

        # Distance from this job back to depot (to check feasibility)
        return_dist = haversine_m(job.latitude, job.longitude,
                                  depot_lat, depot_lon)
        return_travel = travel_time_min(return_dist, speed_mpm)

        candidate_time = total_time + leg_travel + job.service_time_min + return_travel

        # Capacity check
        if len(visited) >= Q_max:
            dropped.append(job)
            continue

        # Time budget check (including return leg)
        if candidate_time > T_max:
            dropped.append(job)
            continue

        # Accept the stop
        visited.append(job)
        total_dist += leg_dist
        total_time += leg_travel + job.service_time_min
        cur_lat, cur_lon = job.latitude, job.longitude

        # Inter-stop distance flag (guidance only, does not drop)
        if leg_dist > r_interstop:
            cross_area_jobs.append(job.job_id)

    # Add return leg to depot
    if visited:
        ret_dist = haversine_m(cur_lat, cur_lon, depot_lat, depot_lon)
        ret_travel = travel_time_min(ret_dist, speed_mpm)
        total_dist += ret_dist
        total_time += ret_travel

    return visited, dropped, total_dist, total_time, cross_area_jobs


# ── Public API ──────────────────────────────────────────────────────────────


def build_route(
    tech: Technician,
    vehicle: Vehicle,
    day: str,
    jobs: list[Job],
    config: dict[str, Any],
) -> tuple[RouteResult, list[str], list[ReviewFlag]]:
    """Build a single route for one (tech, vehicle, day) bundle.

    1. NN-order the jobs.
    2. Walk the route enforcing T_max and Q_k.
    3. If anything was dropped, re-run NN on the feasible subset only.

    Returns:
        (route_result, dropped_job_ids, review_flags)
    """
    T_max = config.get("T_max_minutes", 480)
    r_interstop = config.get("r_interstop_limit_m", 15_000)
    P_max = config.get("P_max_stops", 14)
    Q_max = min(vehicle.capacity, P_max)

    if not jobs:
        return (
            RouteResult(
                tech_id=tech.tech_id,
                vehicle_id=vehicle.vehicle_id,
                day=day,
                visited_job_ids=[],
                dropped_job_ids=[],
                total_distance_m=0.0,
                total_time_min=0.0,
            ),
            [],
            [],
        )

    # First pass: NN order all jobs
    ordered = _nn_order(tech.home_lat, tech.home_lon, jobs)
    visited, dropped, dist, time_min, cross_jobs = _walk_route(
        tech.home_lat, tech.home_lon, ordered,
        vehicle.speed_mpm, T_max, Q_max, r_interstop,
    )

    # If any jobs dropped, re-run NN on the feasible subset
    if dropped and visited:
        ordered2 = _nn_order(tech.home_lat, tech.home_lon, visited)
        visited, extra_dropped, dist, time_min, cross_jobs = _walk_route(
            tech.home_lat, tech.home_lon, ordered2,
            vehicle.speed_mpm, T_max, Q_max, r_interstop,
        )
        # Any additionally dropped jobs add to the dropped list
        dropped.extend(extra_dropped)

    dropped_ids = [j.job_id for j in dropped]

    # Build review flags
    flags: list[ReviewFlag] = []

    for jid in dropped_ids:
        flags.append(ReviewFlag(
            code="ROUTE_DROP",
            severity="WARN",
            message=(
                f"Job {jid} scheduled by Phase 1 but dropped in Phase 2 "
                f"(travel infeasible for {tech.tech_id}/{vehicle.vehicle_id}/{day})."
            ),
            refs={"job_id": jid, "tech_id": tech.tech_id,
                  "vehicle_id": vehicle.vehicle_id, "day": day},
        ))

    if cross_jobs:
        flags.append(ReviewFlag(
            code="CROSS_AREA",
            severity="INFO",
            message=(
                f"Route {tech.tech_id}/{vehicle.vehicle_id}/{day} has "
                f"{len(cross_jobs)} inter-stop gap(s) > "
                f"{r_interstop/1000:.0f} km: {cross_jobs}."
            ),
            refs={"tech_id": tech.tech_id, "vehicle_id": vehicle.vehicle_id,
                  "day": day, "cross_area_jobs": cross_jobs},
        ))

    if not visited and jobs:
        flags.append(ReviewFlag(
            code="NO_FEASIBLE",
            severity="CRITICAL",
            message=(
                f"Phase 1 bundle {tech.tech_id}/{vehicle.vehicle_id}/{day} "
                f"has no feasible Phase 2 route ({len(jobs)} jobs all dropped)."
            ),
            refs={"tech_id": tech.tech_id, "vehicle_id": vehicle.vehicle_id,
                  "day": day},
        ))

    route = RouteResult(
        tech_id=tech.tech_id,
        vehicle_id=vehicle.vehicle_id,
        day=day,
        visited_job_ids=[j.job_id for j in visited],
        dropped_job_ids=dropped_ids,
        total_distance_m=dist,
        total_time_min=time_min,
    )

    return route, dropped_ids, flags
