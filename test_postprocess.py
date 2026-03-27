"""Tests for pipeline Stage 7: Post-processing.

Covers:
  - Standby ranking: compatible jobs ranked, incompatible excluded
  - Standby ranking: cluster radius filtering
  - Weak-standby flag generation
  - Area readiness levels (Good / Moderate / Lean)
  - DUP_ADDR flag (≥2 jobs at same address)
  - GEOCODE_OOB flag (coordinates outside bounding box)
  - HELPER_TRAVEL flag (helper depot far from primary)
  - generate_review_flags aggregation
  - run_postprocessing end-to-end with example data
"""

from nes_dispatch.data import load_weekly_data
from nes_dispatch.data.models import (
    Exclusion, Job, ReviewFlag, RouteResult,
    ScheduleAssignment, Technician, Vehicle,
)
from nes_dispatch.postprocess.standby import select_standby_per_route
from nes_dispatch.postprocess.readiness import compute_area_readiness
from nes_dispatch.postprocess.flags import (
    flag_dup_addr,
    flag_weak_standby,
    flag_helper_travel,
    flag_geocode_oob,
    generate_review_flags,
)
from nes_dispatch.pipeline import (
    apply_exclusion_filters,
    apply_exceptions,
    compute_consumed_capacity,
    run_phase1_schedule,
    run_phase2_routing,
    run_postprocessing,
    split_special_routes,
    plan_special_routes,
)

# ── Shared config ────────────────────────────────────────────────────────────
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

# ── Synthetic fixtures ───────────────────────────────────────────────────────
_tech_a = Technician("T-A", "Alice", ["boiler_service"], 43.20, -71.50, ["Mon", "Tue"])
_tech_b = Technician("T-B", "Bob", ["boiler_service", "install"], 43.25, -71.55, ["Mon", "Tue"])
_veh_a = Vehicle("V-A", "van", ["boiler_service"], ["Mon", "Tue"], 450.0, 0.001, 10)

def _job(jid, lat=43.21, lon=-71.51, area="A-1", addr="123 Main St",
         route_type="normal", helper=False, age=10, value=100.0, svc=45.0):
    return Job(jid, addr, lat, lon, area, route_type, helper, age, value, svc, "candidate")

passed = 0

# ═══ Test 1: standby ranking — compatible jobs ══════════════════════════════
# Route visits J1, unassigned J2 and J3 should be ranked as standby
route = RouteResult("T-A", "V-A", "Mon", ["J1"], [], 5000.0, 60.0)
j1 = _job("J1")
j2 = _job("J2", lat=43.22, lon=-71.52)  # close to centroid
j3 = _job("J3", lat=43.24, lon=-71.54)  # farther
unassigned = [j2, j3]

standby = select_standby_per_route(
    [route], unassigned, [_tech_a], [_veh_a], config,
)
key = ("T-A", "V-A", "Mon")
assert key in standby, f"Expected key {key} in standby"
assert standby[key][0] == "J2", f"J2 should rank first (closer), got {standby[key]}"
assert standby[key][1] == "J3", f"J3 should rank second"
passed += 1
print(f"  [PASS] Test 1: standby ranking = {standby[key]}")

# ═══ Test 2: standby — cluster radius filtering ═════════════════════════════
# Job far outside cluster radius should not appear
j_far = _job("J-FAR", lat=45.00, lon=-73.00)  # well beyond 30 km
standby2 = select_standby_per_route(
    [route], [j_far], [_tech_a], [_veh_a], config,
)
assert len(standby2[key]) == 0, f"Far job should be filtered, got {standby2[key]}"
passed += 1
print(f"  [PASS] Test 2: standby cluster radius filter — far job excluded")

# ═══ Test 3: standby — skill mismatch excluded ══════════════════════════════
# Radiator job can't be standby for a boiler_service tech
j_rad = _job("J-RAD", route_type="radiator")
standby3 = select_standby_per_route(
    [route], [j_rad], [_tech_a], [_veh_a], config,
)
assert len(standby3[key]) == 0, f"Radiator job should be excluded for boiler tech"
passed += 1
print(f"  [PASS] Test 3: standby skill mismatch excluded")

# ═══ Test 4: weak standby flag ══════════════════════════════════════════════
# Only 1 standby candidate, threshold = 2 → should flag
standby_low = {("T-A", "V-A", "Mon"): ["J2"]}
flags_ws = flag_weak_standby(standby_low, config)
assert len(flags_ws) == 1
assert flags_ws[0].code == "WEAK_STANDBY"
assert flags_ws[0].severity == "WARN"
passed += 1
print(f"  [PASS] Test 4: WEAK_STANDBY flag for 1 candidate (threshold=2)")

# ═══ Test 5: weak standby — above threshold → no flag ═══════════════════════
standby_ok = {("T-A", "V-A", "Mon"): ["J2", "J3", "J4"]}
flags_ws2 = flag_weak_standby(standby_ok, config)
assert len(flags_ws2) == 0, f"3 candidates ≥ threshold 2, should not flag"
passed += 1
print(f"  [PASS] Test 5: no WEAK_STANDBY flag when candidates ≥ threshold")

# ═══ Test 6: area readiness — Good / Moderate / Lean ════════════════════════
# Area A-1: 3 jobs, 3 visited → ratio 1.0 → "Good" (if standby avg ≥ 2)
# Area A-2: 3 jobs, 1 visited → ratio 0.33 → depends on standby
j_a1 = [_job(f"G-{i}", area="A-1") for i in range(3)]
j_a2 = [_job(f"G-{i+3}", area="A-2") for i in range(3)]
all_cand = j_a1 + j_a2

route_g = RouteResult("T-A", "V-A", "Mon",
                       ["G-0", "G-1", "G-2", "G-3"], [], 5000.0, 60.0)
standby_g = {("T-A", "V-A", "Mon"): ["G-4", "G-5"]}  # avg 2

readiness = compute_area_readiness([route_g], standby_g, all_cand, config)
assert readiness["A-1"] == "Good", f"A-1 ratio=1.0, standby≥2 → Good, got {readiness['A-1']}"
assert readiness["A-2"] == "Moderate", f"A-2 ratio=0.33 but standby≥2 → Moderate, got {readiness['A-2']}"
passed += 1
print(f"  [PASS] Test 6: readiness A-1={readiness['A-1']}, A-2={readiness['A-2']}")

# ═══ Test 7: area readiness — Lean ══════════════════════════════════════════
# No jobs visited, no standby → Lean
route_empty = RouteResult("T-A", "V-A", "Mon", [], [], 0.0, 0.0)
readiness_lean = compute_area_readiness(
    [route_empty], {("T-A", "V-A", "Mon"): []}, j_a1, config,
)
assert readiness_lean["A-1"] == "Lean", f"0% assigned, 0 standby → Lean, got {readiness_lean['A-1']}"
passed += 1
print(f"  [PASS] Test 7: readiness Lean = {readiness_lean['A-1']}")

# ═══ Test 8: DUP_ADDR flag ══════════════════════════════════════════════════
dup_jobs = [
    _job("D-1", addr="123 Main St"),
    _job("D-2", addr="123 main st"),  # case-insensitive match
    _job("D-3", addr="456 Oak Ave"),
]
flags_dup = flag_dup_addr(dup_jobs)
assert len(flags_dup) == 1, f"Expected 1 DUP_ADDR, got {len(flags_dup)}"
assert flags_dup[0].code == "DUP_ADDR"
assert flags_dup[0].severity == "INFO"
assert "D-1" in flags_dup[0].refs["job_ids"]
assert "D-2" in flags_dup[0].refs["job_ids"]
passed += 1
print(f"  [PASS] Test 8: DUP_ADDR flag for shared address")

# ═══ Test 9: GEOCODE_OOB flag ═══════════════════════════════════════════════
oob_jobs = [
    _job("OOB-1", lat=40.0, lon=-71.0),  # lat below 41
    _job("OOB-2", lat=49.0, lon=-71.0),  # lat above 48
    _job("OK-1", lat=43.0, lon=-71.0),   # inside bounds
]
flags_oob = flag_geocode_oob(oob_jobs, config)
assert len(flags_oob) == 2, f"Expected 2 OOB flags, got {len(flags_oob)}"
codes = [f.code for f in flags_oob]
assert all(c == "GEOCODE_OOB" for c in codes)
assert all(f.severity == "CRITICAL" for f in flags_oob)
passed += 1
print(f"  [PASS] Test 9: GEOCODE_OOB for 2 out-of-bounds jobs")

# ═══ Test 10: HELPER_TRAVEL flag ════════════════════════════════════════════
# Helper tech far from primary → flag
tech_far = Technician("T-FAR", "Far", ["boiler_service"], 45.0, -73.0, ["Mon"])
assignments_ht = [
    ScheduleAssignment("J1", "T-A", "V-A", "Mon", helper_tech_id="T-FAR"),
]
flags_ht = flag_helper_travel(assignments_ht, [_tech_a, tech_far], config)
assert len(flags_ht) == 1
assert flags_ht[0].code == "HELPER_TRAVEL"
assert flags_ht[0].severity == "WARN"
assert flags_ht[0].refs["helper_tech_id"] == "T-FAR"
passed += 1
print(f"  [PASS] Test 10: HELPER_TRAVEL flag for distant helper")

# ═══ Test 11: HELPER_TRAVEL — close helper → no flag ════════════════════════
assignments_close = [
    ScheduleAssignment("J1", "T-A", "V-A", "Mon", helper_tech_id="T-B"),
]
flags_ht2 = flag_helper_travel(assignments_close, [_tech_a, _tech_b], config)
assert len(flags_ht2) == 0, f"Close helper should not flag, got {len(flags_ht2)}"
passed += 1
print(f"  [PASS] Test 11: no HELPER_TRAVEL for close helper")

# ═══ Test 12: generate_review_flags aggregation ═════════════════════════════
all_flags = generate_review_flags(
    candidate_jobs=dup_jobs + oob_jobs,
    assignments=assignments_ht,
    technicians=[_tech_a, tech_far],
    standby=standby_low,
    config=config,
)
flag_codes = [f.code for f in all_flags]
assert "DUP_ADDR" in flag_codes
assert "GEOCODE_OOB" in flag_codes
assert "HELPER_TRAVEL" in flag_codes
assert "WEAK_STANDBY" in flag_codes
passed += 1
print(f"  [PASS] Test 12: generate_review_flags has all 4 codes: {sorted(set(flag_codes))}")

# ═══ Test 13: run_postprocessing end-to-end with example data ═══════════════
wd = load_weekly_data("data")  # 25 jobs, 4 techs, 5 vehicles

# Run stages 2–6 to get routes and assignments
candidates, excl_s2 = apply_exclusion_filters(wd.jobs)
apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)
special, normal = split_special_routes(candidates)
sp_assign, sp_excl = plan_special_routes(special, wd.technicians, wd.vehicles, config)
jobs_lookup = {j.job_id: j for j in wd.jobs}
consumed = compute_consumed_capacity(sp_assign, jobs_lookup)
ph1_assign, ph1_excl, wk_flags = run_phase1_schedule(
    normal, wd.technicians, wd.vehicles, config, consumed,
)
all_assign = sp_assign + ph1_assign
routes, ph2_excl, ph2_flags = run_phase2_routing(
    all_assign, wd.technicians, wd.vehicles, jobs_lookup, config,
)

# Run postprocessing
standby_e2e, readiness_e2e, flags_e2e = run_postprocessing(
    routes, candidates, all_assign, wd.technicians, wd.vehicles, config,
)

# Basic sanity checks
assert isinstance(standby_e2e, dict), "standby should be a dict"
assert isinstance(readiness_e2e, dict), "readiness should be a dict"
assert isinstance(flags_e2e, list), "flags should be a list"

# Every route should have a standby entry
for r in routes:
    key = (r.tech_id, r.vehicle_id, r.day)
    assert key in standby_e2e, f"Missing standby entry for {key}"

# Every area with candidates should have a readiness level
area_ids = {j.area_id for j in candidates}
for a in area_ids:
    assert a in readiness_e2e, f"Missing readiness for area {a}"
    assert readiness_e2e[a] in {"Good", "Moderate", "Lean"}, f"Bad level: {readiness_e2e[a]}"

# All flags should be ReviewFlag instances
for f in flags_e2e:
    assert isinstance(f, ReviewFlag)
    assert f.severity in {"INFO", "WARN", "CRITICAL"}

passed += 1
print(f"  [PASS] Test 13: end-to-end postprocessing — "
      f"{len(standby_e2e)} standby entries, "
      f"{len(readiness_e2e)} areas, "
      f"{len(flags_e2e)} flags")

# ═══ Summary ════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  test_postprocess.py: {passed}/13 tests passed")
print(f"{'='*60}")
assert passed == 13, f"FAIL — only {passed}/13 passed"
