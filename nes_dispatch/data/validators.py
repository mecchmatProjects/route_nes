"""Pre-run input validation.

Checks from Technical Sketch §5 Stage 1:
  - Required CSV columns present
  - Coordinates within NE bounding box
  - Referential integrity (exception scope_id → tech/vehicle)
  - No duplicate primary keys
  - Config schema valid (all keys present, in range)
  - At least one feasible (tech, vehicle, day) triple after exceptions
"""

from __future__ import annotations

from typing import Any

from .models import WeeklyData, ReviewFlag


# ── Helpers ─────────────────────────────────────────────────────────────────

VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri"}
VALID_ROUTE_TYPES = {"normal", "radiator", "nh_overnight", "helper"}
VALID_STATUSES = {"candidate", "excluded", "cancelled", "assigned"}
VALID_SCOPE_TYPES = {"technician", "vehicle"}
VALID_EFFECT_TYPES = {"unavailable", "partial"}

REQUIRED_CONFIG_KEYS = {
    "T_max_minutes", "T_max_phase1_fraction", "P_max_stops",
    "R_cluster_radius_m", "r_interstop_limit_m",
    "seasonal_weights", "summer_months",
    "tech_overload_pct", "veh_bottleneck_days", "weak_standby_threshold",
    "lat_bounds", "lon_bounds",
}


def _effective_days(
    base_days: list[str],
    entity_id: str,
    scope_type: str,
    wd: WeeklyData,
) -> set[str]:
    """Return available days after removing 'unavailable' exceptions."""
    removed = {
        ex.day
        for ex in wd.exceptions
        if ex.scope_type == scope_type
        and ex.scope_id == entity_id
        and ex.effect_type == "unavailable"
    }
    return set(base_days) - removed


# ── Public API ──────────────────────────────────────────────────────────────


def validate_inputs(
    wd: WeeklyData,
    config: dict[str, Any],
) -> list[str]:
    """Run all Stage-1 validation checks.

    Returns a list of human-readable error strings.  An empty list means the
    data is clean enough to proceed.
    """
    errors: list[str] = []

    # 1. Duplicate primary keys ──────────────────────────────────────────────
    _check_duplicates(errors, [j.job_id for j in wd.jobs], "job_id")
    _check_duplicates(errors, [t.tech_id for t in wd.technicians], "tech_id")
    _check_duplicates(errors, [v.vehicle_id for v in wd.vehicles], "vehicle_id")
    _check_duplicates(errors, [e.exception_id for e in wd.exceptions], "exception_id")

    # 2. Coordinate bounds ───────────────────────────────────────────────────
    lat_lo, lat_hi = config.get("lat_bounds", [41.0, 48.0])
    lon_lo, lon_hi = config.get("lon_bounds", [-74.0, -67.0])

    for j in wd.jobs:
        if not (lat_lo <= j.latitude <= lat_hi):
            errors.append(
                f"GEOCODE_OOB: job {j.job_id} latitude {j.latitude} "
                f"outside [{lat_lo}, {lat_hi}]"
            )
        if not (lon_lo <= j.longitude <= lon_hi):
            errors.append(
                f"GEOCODE_OOB: job {j.job_id} longitude {j.longitude} "
                f"outside [{lon_lo}, {lon_hi}]"
            )

    for t in wd.technicians:
        if not (lat_lo <= t.home_lat <= lat_hi):
            errors.append(
                f"GEOCODE_OOB: tech {t.tech_id} home_lat {t.home_lat} "
                f"outside [{lat_lo}, {lat_hi}]"
            )
        if not (lon_lo <= t.home_lon <= lon_hi):
            errors.append(
                f"GEOCODE_OOB: tech {t.tech_id} home_lon {t.home_lon} "
                f"outside [{lon_lo}, {lon_hi}]"
            )

    # 3. Enum / value sanity ─────────────────────────────────────────────────
    for j in wd.jobs:
        if j.route_type not in VALID_ROUTE_TYPES:
            errors.append(
                f"INVALID_ROUTE_TYPE: job {j.job_id} has '{j.route_type}'"
            )
        if j.status not in VALID_STATUSES:
            errors.append(
                f"INVALID_STATUS: job {j.job_id} has '{j.status}'"
            )
        if j.service_time_min < 0:
            errors.append(
                f"NEGATIVE_SERVICE_TIME: job {j.job_id}"
            )
        if j.value < 0:
            errors.append(f"NEGATIVE_VALUE: job {j.job_id}")

    for t in wd.technicians:
        for day in t.available_days:
            if day not in VALID_DAYS:
                errors.append(
                    f"INVALID_DAY: tech {t.tech_id} has '{day}'"
                )

    for v in wd.vehicles:
        for day in v.available_days:
            if day not in VALID_DAYS:
                errors.append(
                    f"INVALID_DAY: vehicle {v.vehicle_id} has '{day}'"
                )
        if v.capacity <= 0:
            errors.append(
                f"INVALID_CAPACITY: vehicle {v.vehicle_id} capacity={v.capacity}"
            )

    for ex in wd.exceptions:
        if ex.scope_type not in VALID_SCOPE_TYPES:
            errors.append(
                f"INVALID_SCOPE_TYPE: exception {ex.exception_id} "
                f"has '{ex.scope_type}'"
            )
        if ex.effect_type not in VALID_EFFECT_TYPES:
            errors.append(
                f"INVALID_EFFECT_TYPE: exception {ex.exception_id} "
                f"has '{ex.effect_type}'"
            )
        if ex.day not in VALID_DAYS:
            errors.append(
                f"INVALID_DAY: exception {ex.exception_id} has '{ex.day}'"
            )

    # 4. Referential integrity — exception scope_ids ─────────────────────────
    tech_ids = {t.tech_id for t in wd.technicians}
    veh_ids = {v.vehicle_id for v in wd.vehicles}

    for ex in wd.exceptions:
        if ex.scope_type == "technician" and ex.scope_id not in tech_ids:
            errors.append(
                f"REF_INTEGRITY: exception {ex.exception_id} references "
                f"unknown tech '{ex.scope_id}'"
            )
        if ex.scope_type == "vehicle" and ex.scope_id not in veh_ids:
            errors.append(
                f"REF_INTEGRITY: exception {ex.exception_id} references "
                f"unknown vehicle '{ex.scope_id}'"
            )

    # 5. Config schema ───────────────────────────────────────────────────────
    missing_keys = REQUIRED_CONFIG_KEYS - set(config.keys())
    if missing_keys:
        errors.append(f"CONFIG_MISSING_KEYS: {sorted(missing_keys)}")

    if "T_max_minutes" in config and config["T_max_minutes"] <= 0:
        errors.append("CONFIG_RANGE: T_max_minutes must be > 0")
    if "T_max_phase1_fraction" in config:
        frac = config["T_max_phase1_fraction"]
        if not (0.0 < frac <= 1.0):
            errors.append("CONFIG_RANGE: T_max_phase1_fraction must be in (0, 1]")
    if "P_max_stops" in config and config["P_max_stops"] <= 0:
        errors.append("CONFIG_RANGE: P_max_stops must be > 0")
    if "R_cluster_radius_m" in config and config["R_cluster_radius_m"] <= 0:
        errors.append("CONFIG_RANGE: R_cluster_radius_m must be > 0")

    # 6. At least one feasible (tech, vehicle, day) triple ───────────────────
    if not errors:  # only if data is otherwise clean
        has_feasible = False
        for t in wd.technicians:
            t_days = _effective_days(t.available_days, t.tech_id, "technician", wd)
            for v in wd.vehicles:
                v_days = _effective_days(v.available_days, v.vehicle_id, "vehicle", wd)
                if t_days & v_days:
                    has_feasible = True
                    break
            if has_feasible:
                break
        if not has_feasible:
            errors.append(
                "NO_FEASIBLE_TRIPLE: no (technician, vehicle, day) combination "
                "remains after applying exceptions"
            )

    return errors


# ── Internal helpers ────────────────────────────────────────────────────────


def _check_duplicates(
    errors: list[str], ids: list[str], label: str
) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for pk in ids:
        if pk in seen:
            dupes.add(pk)
        seen.add(pk)
    if dupes:
        errors.append(f"DUPLICATE_{label.upper()}: {sorted(dupes)}")
