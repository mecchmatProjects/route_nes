"""10 named eligibility rules (Technical Sketch §5, Stage 5.2).

Each rule is a standalone function:
    rule(job, tech, vehicle, day, ...) → (pass: bool, rule_name: str)

check_eligibility() evaluates all 10 rules for a (job, tech, vehicle, day)
slot and returns the list of failing rule names (empty = eligible).
"""

from __future__ import annotations

import math
from typing import Any

from ..data.models import Job, Technician, Vehicle

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ── Skill / capability requirement mapping ──────────────────────────────────

def _required_skills(job: Job) -> set[str]:
    if job.route_type == "radiator":
        return {"radiator"}
    if job.route_type == "nh_overnight":
        return {"overhaul"}
    if job.route_type == "helper" or job.helper_needed:
        return {"install"}
    return {"boiler_service"}


def _required_capabilities(job: Job) -> set[str]:
    if job.route_type == "radiator":
        return {"radiator"}
    if job.route_type == "nh_overnight":
        return {"overhaul"}
    if job.route_type == "helper" or job.helper_needed:
        return {"install"}
    return {"boiler_service"}


# ── Individual rules ────────────────────────────────────────────────────────

def tech_available(day: str, tech: Technician) -> bool:
    """TECH_AVAILABLE: d ∈ D_t"""
    return day in tech.available_days


def veh_available(day: str, vehicle: Vehicle) -> bool:
    """VEH_AVAILABLE: d ∈ D_k"""
    return day in vehicle.available_days


def skill_match(tech: Technician, job: Job) -> bool:
    """SKILL_MATCH: skill_t ⊇ req(j)"""
    return _required_skills(job).issubset(set(tech.skills))


def veh_capability(vehicle: Vehicle, job: Job) -> bool:
    """VEH_CAPABILITY: cap_k ⊇ ρ_j"""
    return _required_capabilities(job).issubset(set(vehicle.capability_tags))


def within_radius(
    tech: Technician, job: Job, R: float,
) -> bool:
    """WITHIN_RADIUS: haversine(depot_t, job_j) ≤ R"""
    return _haversine_m(
        tech.home_lat, tech.home_lon, job.latitude, job.longitude
    ) <= R


def not_prohibited(
    tech: Technician, job: Job,
    prohibited_pairs: set[tuple[str, str]],
) -> bool:
    """NOT_PROHIBITED: (t, j) ∉ prohibited pairs"""
    return (tech.tech_id, job.job_id) not in prohibited_pairs


def capacity_ok(
    vehicle: Vehicle,
    day: str,
    stop_count: dict[tuple[str, str], int],
    P_max: int,
) -> bool:
    """CAPACITY_OK: current stops for (k, d) < min(Q_k, P_max)"""
    current = stop_count.get((vehicle.vehicle_id, day), 0)
    return current < min(vehicle.capacity, P_max)


def time_ok(
    tech: Technician,
    day: str,
    job: Job,
    service_mins: dict[tuple[str, str], float],
    time_budget: float,
) -> bool:
    """TIME_OK: current service time for (t, d) + τ_j ≤ time_budget"""
    current = service_mins.get((tech.tech_id, day), 0.0)
    return current + job.service_time_min <= time_budget


def one_veh_per_tech(
    tech: Technician,
    vehicle: Vehicle,
    day: str,
    tech_veh: dict[tuple[str, str], str],
) -> bool:
    """ONE_VEH_PER_TECH: tech not already using a different vehicle on day."""
    existing = tech_veh.get((tech.tech_id, day))
    return existing is None or existing == vehicle.vehicle_id


def one_tech_per_veh(
    tech: Technician,
    vehicle: Vehicle,
    day: str,
    veh_tech: dict[tuple[str, str], str],
) -> bool:
    """ONE_TECH_PER_VEH: vehicle not already assigned to a different tech."""
    existing = veh_tech.get((vehicle.vehicle_id, day))
    return existing is None or existing == tech.tech_id


# ── Combined check ──────────────────────────────────────────────────────────

def check_eligibility(
    job: Job,
    tech: Technician,
    vehicle: Vehicle,
    day: str,
    config: dict[str, Any],
    stop_count: dict[tuple[str, str], int],
    service_mins: dict[tuple[str, str], float],
    tech_veh: dict[tuple[str, str], str],
    veh_tech: dict[tuple[str, str], str],
    prohibited_pairs: set[tuple[str, str]] | None = None,
) -> list[str]:
    """Evaluate all 10 eligibility rules for a (job, tech, vehicle, day) slot.

    Returns a list of *failing* rule names.  Empty list ⟹ slot is eligible.
    """
    if prohibited_pairs is None:
        prohibited_pairs = set()

    R = config.get("R_cluster_radius_m", 30_000)
    P_max = config.get("P_max_stops", 14)
    T_max = config.get("T_max_minutes", 480)
    phase1_frac = config.get("T_max_phase1_fraction", 0.80)
    budget = T_max * phase1_frac

    failures: list[str] = []

    if not tech_available(day, tech):
        failures.append("TECH_AVAILABLE")
    if not veh_available(day, vehicle):
        failures.append("VEH_AVAILABLE")
    if not skill_match(tech, job):
        failures.append("SKILL_MATCH")
    if not veh_capability(vehicle, job):
        failures.append("VEH_CAPABILITY")
    if not within_radius(tech, job, R):
        failures.append("WITHIN_RADIUS")
    if not not_prohibited(tech, job, prohibited_pairs):
        failures.append("NOT_PROHIBITED")
    if not capacity_ok(vehicle, day, stop_count, P_max):
        failures.append("CAPACITY_OK")
    if not time_ok(tech, day, job, service_mins, budget):
        failures.append("TIME_OK")
    if not one_veh_per_tech(tech, vehicle, day, tech_veh):
        failures.append("ONE_VEH_PER_TECH")
    if not one_tech_per_veh(tech, vehicle, day, veh_tech):
        failures.append("ONE_TECH_PER_VEH")

    return failures
