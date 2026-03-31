"""Smoke-test for nes_dispatch.data — load & validate."""

import copy
from nes_dispatch.data import load_weekly_data, validate_inputs

# ── Load ────────────────────────────────────────────────────────────────────
wd = load_weekly_data("data")
print(f"Loaded: {len(wd.jobs)} jobs, {len(wd.technicians)} techs, "
      f"{len(wd.vehicles)} vehicles, {len(wd.exceptions)} exceptions")

j = wd.jobs[0]
print(f"Job[0]: {j.job_id}  addr={j.address!r}  lat={j.latitude}  "
      f"lon={j.longitude}  type={j.route_type}  helper={j.helper_needed}")
t = wd.technicians[0]
print(f"Tech[0]: {t.tech_id}  name={t.name!r}  skills={t.skills}  "
      f"days={t.available_days}")
v = wd.vehicles[0]
print(f"Veh[0]: {v.vehicle_id}  type={v.vehicle_type}  "
      f"tags={v.capability_tags}  cap={v.capacity}")
e = wd.exceptions[0]
print(f"Exc[0]: {e.exception_id}  {e.scope_type}/{e.scope_id}  "
      f"{e.day}  {e.effect_type}")
print()

# ── Config ──────────────────────────────────────────────────────────────────
config = {
    "T_max_minutes": 480,
    "T_max_phase1_fraction": 0.80,
    "P_max_stops": 14,
    "R_cluster_radius_m": 30000,
    "r_interstop_limit_m": 15000,
    "seasonal_weights": {
        "summer": {"w_g": 0.4, "w_f": 0.2, "w_a": 0.3, "w_r": 0.1},
        "winter": {"w_g": 0.2, "w_f": 0.4, "w_a": 0.3, "w_r": 0.1},
    },
    "summer_months": [3, 4, 5, 6, 7, 8, 9],
    "tech_overload_pct": 0.90,
    "veh_bottleneck_days": 4,
    "weak_standby_threshold": 2,
    "lat_bounds": [41.0, 48.0],
    "lon_bounds": [-74.0, -67.0],
}

# ── Test 1: good data + good config → no errors ────────────────────────────
errors = validate_inputs(wd, config)
assert errors == [], f"Expected no errors, got: {errors}"
print("TEST 1 PASS — valid data, no errors")

# ── Test 2: missing config key ──────────────────────────────────────────────
bad_config = dict(config)
del bad_config["T_max_minutes"]
errors = validate_inputs(wd, bad_config)
assert any("CONFIG_MISSING" in e for e in errors), f"Expected CONFIG_MISSING, got: {errors}"
print(f"TEST 2 PASS — missing config key detected: {errors[0]}")

# ── Test 3: out-of-bounds coordinate ────────────────────────────────────────
wd3 = copy.deepcopy(wd)
wd3.jobs[0].latitude = 99.0
errors = validate_inputs(wd3, config)
geocode_errs = [e for e in errors if "GEOCODE" in e]
assert geocode_errs, f"Expected GEOCODE_OOB, got: {errors}"
print(f"TEST 3 PASS — bad coordinate detected: {geocode_errs[0]}")

# ── Test 4: duplicate primary key ───────────────────────────────────────────
wd4 = copy.deepcopy(wd)
wd4.jobs[1].job_id = wd4.jobs[0].job_id
errors = validate_inputs(wd4, config)
dup_errs = [e for e in errors if "DUPLICATE" in e]
assert dup_errs, f"Expected DUPLICATE, got: {errors}"
print(f"TEST 4 PASS — duplicate PK detected: {dup_errs[0]}")

# ── Test 5: bad referential integrity ───────────────────────────────────────
wd5 = copy.deepcopy(wd)
wd5.exceptions[0].tech_or_slot = "T-GHOST"
errors = validate_inputs(wd5, config)
ref_errs = [e for e in errors if "REF_INTEGRITY" in e]
assert ref_errs, f"Expected REF_INTEGRITY, got: {errors}"
print(f"TEST 5 PASS — bad ref detected: {ref_errs[0]}")

# ── Test 6: invalid job_category ────────────────────────────────────────────
wd6 = copy.deepcopy(wd)
wd6.jobs[0].job_category = "Bogus Category"
errors = validate_inputs(wd6, config)
type_errs = [e for e in errors if "INVALID_CATEGORY" in e]
assert type_errs, f"Expected INVALID_CATEGORY, got: {errors}"
print(f"TEST 6 PASS — invalid job_category detected: {type_errs[0]}")

# ── Test 7: config range violation ──────────────────────────────────────────
bad_config2 = dict(config)
bad_config2["T_max_minutes"] = -10
errors = validate_inputs(wd, bad_config2)
range_errs = [e for e in errors if "CONFIG_RANGE" in e]
assert range_errs, f"Expected CONFIG_RANGE, got: {errors}"
print(f"TEST 7 PASS — config range error detected: {range_errs[0]}")

print()
print("ALL 7 TESTS PASSED")
