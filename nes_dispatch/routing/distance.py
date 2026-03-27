"""Distance computation (Technical Sketch §2, routing/distance.py).

Provides haversine distance and travel-time helpers used by the
nearest-neighbour sequencer and feasibility verifier.
"""

from __future__ import annotations

import math

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def travel_time_min(distance_m: float, speed_mpm: float) -> float:
    """Travel time in minutes for *distance_m* at *speed_mpm* (metres/min)."""
    if speed_mpm <= 0:
        return float("inf")
    return distance_m / speed_mpm
