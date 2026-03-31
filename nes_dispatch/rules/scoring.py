"""Queue-based decision-ladder scoring (spec §6.1).

Replaces the earlier composite weighted formula.  The spec explicitly says:
"Use a short decision-ladder scoring model rather than a large point system."

Winter ranking:  Priority → 2x-average Normal → Accepted Quotes = Requested
                 Scheduling (better route wins) → Normal
Summer ranking:  Priority → Accepted Quotes = Requested Scheduling (route
                 quality decides) → Normal

Within each tier, geography (proximity) is used as the tiebreaker.
Scheduling Preferences jobs are treated as an early-pass constraint/review
pool per spec §4; they rank with their effective queue tier.
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
    """Job wrapper carrying the decision-ladder score."""
    job: Job
    score: float          # composite for sort: tier_score + geo tiebreaker
    geo: float            # proximity sub-score ∈ [0,1] (tiebreaker)
    fair: float           # kept for back-compat; = 0.0 in ladder mode
    age: float            # age sub-score ∈ [0,1] (used in winter tiebreak)
    readiness: float      # kept for back-compat; = 0.0 in ladder mode


def _get_season(config: dict[str, Any]) -> str:
    """Return 'summer' or 'winter'.

    Prefers the explicit ``season`` key injected from WeeklyContext.
    Falls back to current-month heuristic only when no explicit season
    is provided (spec §5 / addendum Table 4: Season is a required input).
    """
    explicit = config.get("season")
    if explicit:
        return explicit.lower()
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


_AGE_CEILING_DAYS = 60  # age_days at which the age sub-score saturates at 1.0


def _age_score(job: Job) -> float:
    """Age-based sub-score ∈ [0, 1].  Used as winter tiebreaker."""
    return min(job.age_days / _AGE_CEILING_DAYS, 1.0)


# ── Decision-ladder tier scores ─────────────────────────────────────────────
# Higher tier → higher base score.  Tiebreaker (geo ∈ [0,1]) is added within.

_TIER_PRIORITY          = 5000.0  # Priority queue — always first
_TIER_2X_AVERAGE        = 4000.0  # 2x-average Normal (winter only)
_TIER_AQ_RS             = 3000.0  # Accepted Quotes = Requested Scheduling
_TIER_SCHED_PREF        = 2500.0  # Scheduling Preferences (early-pass pool)
_TIER_NORMAL            = 1000.0  # Normal jobs


def _ladder_tier(job: Job, season: str) -> float:
    """Return the base tier score for *job* based on queue and season."""
    q = job.queue

    if q == "Priority":
        return _TIER_PRIORITY

    if season == "winter" and q == "Normal jobs" and job.avg_wait_2x_flag:
        return _TIER_2X_AVERAGE

    if q in ("Accepted Quotes", "Requested Scheduling"):
        return _TIER_AQ_RS

    if q == "Scheduling Preferences":
        return _TIER_SCHED_PREF

    # Normal jobs (default)
    return _TIER_NORMAL


# ── Public API ──────────────────────────────────────────────────────────────


def score_jobs(
    jobs: list[Job],
    technicians: list[Technician],
    config: dict[str, Any],
    area_assigned_counts: dict[str, int] | None = None,
) -> list[ScoredJob]:
    """Score all *jobs* using the queue-based decision ladder.

    Within each tier:
      - Winter: older jobs preferred (age tiebreaker), then geography.
      - Summer: geography/route quality preferred, then age.

    Returns a list of ScoredJob, **not** yet sorted (caller sorts).
    """
    if area_assigned_counts is None:
        area_assigned_counts = {}

    season = _get_season(config)
    R = config.get("R_cluster_radius_m", 30_000)

    scored: list[ScoredJob] = []
    for j in jobs:
        tier = _ladder_tier(j, season)
        geo = _geo_score(j, technicians, R)
        age = _age_score(j)

        # Tiebreaker within a tier:
        #   Winter: age matters more → 0.6·age + 0.4·geo
        #   Summer: geography matters more → 0.7·geo + 0.3·age
        if season == "winter":
            tiebreak = 0.6 * age + 0.4 * geo
        else:
            tiebreak = 0.7 * geo + 0.3 * age

        composite = tier + tiebreak  # tier dominates; tiebreak only within tier

        scored.append(ScoredJob(
            job=j, score=composite, geo=geo,
            fair=0.0, age=age, readiness=0.0,
        ))

    return scored
