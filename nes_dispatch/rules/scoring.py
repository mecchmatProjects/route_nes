"""Composite priority-score formula (Technical Sketch §5, Stage 5.1).

score_j = w_g·geo_j + w_f·fair_j + w_a·age_j + w_r·readiness_j

All four components are normalised to [0, 1].
Seasonal weights come from config["seasonal_weights"].
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..data.models import Job, Technician

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass
class ScoredJob:
    """Job wrapper carrying the computed composite score."""
    job: Job
    score: float
    geo: float
    fair: float
    age: float
    readiness: float


def _get_season(config: dict[str, Any]) -> str:
    """Return 'summer' or 'winter' based on the current month and config."""
    month = date.today().month
    summer_months = config.get("summer_months", [3, 4, 5, 6, 7, 8, 9])
    return "summer" if month in summer_months else "winter"


def _geo_score(
    job: Job,
    technicians: list[Technician],
    R: float,
) -> float:
    """Geographic proximity score ∈ [0, 1].

    1.0 = job sits right at the nearest technician depot.
    0.0 = job is at or beyond the cluster radius R.
    """
    if not technicians:
        return 0.0
    min_dist = min(
        _haversine_m(t.home_lat, t.home_lon, job.latitude, job.longitude)
        for t in technicians
    )
    if R <= 0:
        return 0.0
    return max(0.0, 1.0 - min_dist / R)


def _fair_score(job: Job, max_value: float) -> float:
    """Fairness / value-normalised score ∈ [0, 1].

    Higher-value jobs receive a higher fairness contribution so that
    revenue-significant work is not indefinitely deferred.
    """
    if max_value <= 0:
        return 0.0
    return min(job.value / max_value, 1.0)


_AGE_CEILING_DAYS = 60  # age_days at which the score saturates at 1.0


def _age_score(job: Job) -> float:
    """Age-based urgency score ∈ [0, 1].

    Linearly ramps from 0 at age 0 to 1 at _AGE_CEILING_DAYS.
    """
    return min(job.age_days / _AGE_CEILING_DAYS, 1.0)


def _readiness_score(
    job: Job,
    area_job_counts: dict[str, int],
    area_assigned_counts: dict[str, int],
) -> float:
    """Area-readiness score ∈ [0, 1].

    Prioritises jobs in areas that have the *fewest* already-assigned jobs
    relative to total candidates.  An area with 0% coverage returns 1.0;
    an area fully covered returns 0.0.
    """
    total = area_job_counts.get(job.area_id, 0)
    if total <= 0:
        return 0.5  # unknown area → neutral
    assigned = area_assigned_counts.get(job.area_id, 0)
    coverage = assigned / total
    return max(0.0, 1.0 - coverage)


# ── Public API ──────────────────────────────────────────────────────────────


def score_jobs(
    jobs: list[Job],
    technicians: list[Technician],
    config: dict[str, Any],
    area_assigned_counts: dict[str, int] | None = None,
) -> list[ScoredJob]:
    """Compute composite priority scores for all *jobs*.

    Returns a list of ScoredJob, **not** yet sorted (caller sorts).
    """
    if area_assigned_counts is None:
        area_assigned_counts = {}

    season = _get_season(config)
    weights = config.get("seasonal_weights", {}).get(season, {})
    w_g = weights.get("w_g", 0.3)
    w_f = weights.get("w_f", 0.3)
    w_a = weights.get("w_a", 0.3)
    w_r = weights.get("w_r", 0.1)

    R = config.get("R_cluster_radius_m", 30_000)

    # Pre-compute area job counts for readiness
    area_job_counts: dict[str, int] = {}
    for j in jobs:
        area_job_counts[j.area_id] = area_job_counts.get(j.area_id, 0) + 1

    max_value = max((j.value for j in jobs), default=0.0)

    scored: list[ScoredJob] = []
    for j in jobs:
        g = _geo_score(j, technicians, R)
        f = _fair_score(j, max_value)
        a = _age_score(j)
        r = _readiness_score(j, area_job_counts, area_assigned_counts)

        composite = w_g * g + w_f * f + w_a * a + w_r * r
        scored.append(ScoredJob(job=j, score=composite, geo=g, fair=f,
                                age=a, readiness=r))

    return scored
