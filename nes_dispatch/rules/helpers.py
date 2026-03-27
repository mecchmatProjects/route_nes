"""Helper-assignment pass (Technical Sketch §5, Stage 5.4).

For helper-needed jobs (j ∈ J^H), find a second technician ≠ primary;
same eligibility checks minus vehicle rules (VEH_AVAILABLE, VEH_CAPABILITY,
CAPACITY_OK, ONE_VEH_PER_TECH, ONE_TECH_PER_VEH).
"""

from __future__ import annotations

from typing import Any

from ..data.models import Job, Technician
from .eligibility import (
    _haversine_m,
    skill_match,
    tech_available,
    within_radius,
    not_prohibited,
    time_ok,
)


def find_helper(
    job: Job,
    day: str,
    primary_tech_id: str,
    technicians: list[Technician],
    config: dict[str, Any],
    service_mins: dict[tuple[str, str], float],
    prohibited_pairs: set[tuple[str, str]] | None = None,
) -> str | None:
    """Find a second technician to assist on *day* for a helper job.

    Applies the same eligibility rules as the main pass **minus** all
    vehicle-related rules:
      ✓ TECH_AVAILABLE, SKILL_MATCH, WITHIN_RADIUS,
        NOT_PROHIBITED, TIME_OK
      ✗ VEH_AVAILABLE, VEH_CAPABILITY, CAPACITY_OK,
        ONE_VEH_PER_TECH, ONE_TECH_PER_VEH

    Among eligible helpers, selects the *closest* to the job site.
    Returns helper tech_id or None.
    """
    if prohibited_pairs is None:
        prohibited_pairs = set()

    R = config.get("R_cluster_radius_m", 30_000)
    T_max = config.get("T_max_minutes", 480)
    phase1_frac = config.get("T_max_phase1_fraction", 0.80)
    budget = T_max * phase1_frac

    best: tuple[float, str] | None = None

    for tech in technicians:
        if tech.tech_id == primary_tech_id:
            continue
        if not tech_available(day, tech):
            continue
        if not skill_match(tech, job):
            continue
        if not within_radius(tech, job, R):
            continue
        if not not_prohibited(tech, job, prohibited_pairs):
            continue
        if not time_ok(tech, day, job, service_mins, budget):
            continue

        dist = _haversine_m(
            tech.home_lat, tech.home_lon, job.latitude, job.longitude
        )
        if best is None or dist < best[0]:
            best = (dist, tech.tech_id)

    return best[1] if best else None
