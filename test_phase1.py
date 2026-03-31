"""Tests for pipeline Stage 5: Phase 1 — Score & Schedule.

Covers:
  - Composite scoring determinism & ordering
  - Individual eligibility rules
  - Slot selection ranking
  - Helper assignment
  - Workload flag generation
  - End-to-end Phase 1 with example data
"""

import copy
from nes_dispatch.data import load_weekly_data
from nes_dispatch.data.models import (
    Exclusion, Job, ReviewFlag, ScheduleAssignment,
    Technician, Vehicle,
)
from nes_dispatch.pipeline import (
    apply_exclusion_filters,
    apply_exceptions,
    compute_consumed_capacity,
    run_phase1_schedule,
    split_special_routes,
    plan_special_routes,
)
from nes_dispatch.rules.scoring import score_jobs, ScoredJob
from nes_dispatch.rules.eligibility import (
    check_eligibility, tech_available, veh_available, skill_match,
    veh_capability, within_radius, not_prohibited, capacity_ok,
    time_ok, one_veh_per_tech, one_tech_per_veh,
)
from nes_dispatch.rules.slot_selection import find_best_eligible_slot, first_failing_rule
from nes_dispatch.rules.helpers import find_helper
from nes_dispatch.rules.workload import check_workload

# ── Setup: run stages 2–4 first ─────────────────────────────────────────────
wd = load_weekly_data("data")
candidates, _ = apply_exclusion_filters(wd.jobs)
apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)

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

special, normal = split_special_routes(candidates)
sp_assignments, sp_exclusions = plan_special_routes(
    special, wd.technicians, wd.vehicles, config
)
jobs_lookup = {j.job_id: j for j in wd.jobs}
consumed = compute_consumed_capacity(sp_assignments, jobs_lookup)

passed = 0

# ═══ Test 1: score_jobs returns ScoredJob list with valid scores ═════════════
scored = score_jobs(normal, wd.technicians, config)
assert len(scored) == len(normal), f"Expected {len(normal)} scored, got {len(scored)}"
for sj in scored:
    assert 0.0 <= sj.score <= 1.0, f"Score {sj.score} out of [0,1] for {sj.job.job_id}"
    assert 0.0 <= sj.geo <= 1.0
    assert 0.0 <= sj.fair <= 1.0
    assert 0.0 <= sj.age <= 1.0
    assert 0.0 <= sj.readiness <= 1.0
passed += 1
print(f"  [PASS] Test 1: score_jobs produces valid scores for {len(scored)} jobs")

# ═══ Test 2: scoring is deterministic ════════════════════════════════════════
scored2 = score_jobs(normal, wd.technicians, config)
for a, b in zip(scored, scored2):
    assert a.score == b.score, f"Non-deterministic score for {a.job.job_id}"
    assert a.job.job_id == b.job.job_id
passed += 1
print("  [PASS] Test 2: scoring is deterministic")

# ═══ Test 3: sorted order respects (-score, -age_days, -value) ═══════════════
scored.sort(key=lambda s: (-s.score, -s.job.age_days, -s.job.value))
for i in range(len(scored) - 1):
    a, b = scored[i], scored[i + 1]
    assert a.score >= b.score or (
        a.score == b.score and a.job.age_days >= b.job.age_days
    ), f"Sort order violated between {a.job.job_id} and {b.job.job_id}"
passed += 1
print("  [PASS] Test 3: sorted order is correct")

# ═══ Test 4: individual eligibility rules ════════════════════════════════════
# Build a synthetic job/tech/veh for targeted rule testing
_t = Technician("T-SYN", "Syn", ["boiler_service"], 43.2, -71.5, ["Mon", "Tue"])
_v = Vehicle("V-SYN", "van", ["boiler_service"], ["Mon", "Tue"], 450, 0.001, 10)
_j = Job(
    job_id="J-SYN", address="123 Test St", city="TestCity", state="RI",
    area_id="01", area_name="A-SYN", job_category="Service Call",
    queue="Normal jobs", latitude=43.21, longitude=-71.51,
    created_date="2026-03-01", age_days=10,
)

assert tech_available("Mon", _t) is True
assert tech_available("Wed", _t) is False
assert veh_available("Tue", _v) is True
assert veh_available("Fri", _v) is False
assert skill_match(_t, _j) is True
assert veh_capability(_v, _j) is True
assert within_radius(_t, _j, 30000) is True
assert not_prohibited(_t, _j, set()) is True
assert not_prohibited(_t, _j, {("T-SYN", "J-SYN")}) is False
assert capacity_ok(_v, "Mon", {}, 14) is True
assert capacity_ok(_v, "Mon", {("V-SYN", "Mon"): 10}, 14) is False
assert time_ok(_t, "Mon", _j, {}, 384.0) is True
assert time_ok(_t, "Mon", _j, {("T-SYN", "Mon"): 350.0}, 384.0) is False
assert one_veh_per_tech(_t, _v, "Mon", {}) is True
assert one_veh_per_tech(_t, _v, "Mon", {("T-SYN", "Mon"): "V-OTHER"}) is False
assert one_tech_per_veh(_t, _v, "Mon", {}) is True
assert one_tech_per_veh(_t, _v, "Mon", {("V-SYN", "Mon"): "T-OTHER"}) is False
passed += 1
print("  [PASS] Test 4: all 10 individual eligibility rules work correctly")

# ═══ Test 5: check_eligibility combined — fully eligible slot ════════════════
failures = check_eligibility(_j, _t, _v, "Mon", config, {}, {}, {}, {})
assert failures == [], f"Expected no failures, got {failures}"
passed += 1
print("  [PASS] Test 5: fully eligible slot returns no failures")

# ═══ Test 6: check_eligibility combined — multiple failures ══════════════════
_t_bad = Technician("T-BAD", "Bad", ["overhaul"], 46.0, -72.0, ["Wed"])
failures_bad = check_eligibility(_j, _t_bad, _v, "Mon", config, {}, {}, {}, {})
assert "TECH_AVAILABLE" in failures_bad
assert "SKILL_MATCH" in failures_bad
assert "WITHIN_RADIUS" in failures_bad
passed += 1
print(f"  [PASS] Test 6: ineligible slot returns {len(failures_bad)} failures: {failures_bad}")

# ═══ Test 7: slot selection returns best fit ═════════════════════════════════
slot = find_best_eligible_slot(
    _j, [_t], [_v], config, {}, {}, {}, {},
)
assert slot is not None, "Expected a valid slot"
assert slot == ("T-SYN", "V-SYN", "Mon") or slot == ("T-SYN", "V-SYN", "Tue"), \
    f"Unexpected slot {slot}"
passed += 1
print(f"  [PASS] Test 7: slot selection returns {slot}")

# ═══ Test 8: slot selection returns None when no eligible slot ════════════════
_t_noskill = Technician("T-NS", "NoSkill", ["overhaul"], 43.2, -71.5, ["Mon"])
slot_none = find_best_eligible_slot(
    _j, [_t_noskill], [_v], config, {}, {}, {}, {},
)
assert slot_none is None, f"Expected None, got {slot_none}"
passed += 1
print("  [PASS] Test 8: slot selection returns None for ineligible combos")

# ═══ Test 9: first_failing_rule returns meaningful code ══════════════════════
reason = first_failing_rule(
    _j, [_t_noskill], [_v], config, {}, {}, {}, {},
)
assert reason == "SKILL_MISMATCH", f"Expected SKILL_MISMATCH, got {reason}"
passed += 1
print(f"  [PASS] Test 9: first_failing_rule → {reason}")

# ═══ Test 10: helper assignment ══════════════════════════════════════════════
_j_helper = Job(
    job_id="J-HLP", address="456 Help St", city="TestCity", state="RI",
    area_id="01", area_name="A-SYN",
    job_category="New Equipment Installation Other Than Boiler",
    queue="Normal jobs", latitude=43.21, longitude=-71.51,
    created_date="2026-03-20", age_days=5, required_job_hours=2.0,
)
_t2 = Technician("T-HLP", "Helper", ["boiler_service", "install"], 43.22, -71.52, ["Mon"])
helper_id = find_helper(
    _j_helper, "Mon", "T-SYN", [_t, _t2], config, {},
)
assert helper_id == "T-HLP", f"Expected T-HLP, got {helper_id}"
passed += 1
print(f"  [PASS] Test 10: helper assignment returns {helper_id}")

# ═══ Test 11: helper returns None when no eligible helper ════════════════════
helper_none = find_helper(
    _j_helper, "Mon", "T-SYN", [_t], config, {},
)
# _t is the primary, no other tech → None
assert helper_none is None, f"Expected None, got {helper_none}"
passed += 1
print("  [PASS] Test 11: helper returns None when unavailable")

# ═══ Test 12: workload review — no flags for light schedule ══════════════════
light_assignments = [
    ScheduleAssignment("J-SYN", "T-SYN", "V-SYN", "Mon"),
]
svc_map = {"J-SYN": 45.0}
flags = check_workload(light_assignments, svc_map, [_t], [_v], config)
assert len(flags) == 0, f"Expected 0 flags, got {len(flags)}"
passed += 1
print("  [PASS] Test 12: light schedule → no workload flags")

# ═══ Test 13: workload review — TECH_OVERLOAD flag ═══════════════════════════
# Give a tech so many minutes they exceed 90% of weekly capacity
# _t has 2 days → weekly capacity = 384 * 2 = 768 min, 90% = 691.2
overload_assignments = [
    ScheduleAssignment(f"OL-{i}", "T-SYN", "V-SYN", "Mon")
    for i in range(8)
]
overload_svc = {f"OL-{i}": 90.0 for i in range(8)}  # 8*90 = 720 > 691.2
flags_ol = check_workload(overload_assignments, overload_svc, [_t], [_v], config)
overload_codes = [f.code for f in flags_ol]
assert "TECH_OVERLOAD" in overload_codes, f"Expected TECH_OVERLOAD, got {overload_codes}"
passed += 1
print("  [PASS] Test 13: TECH_OVERLOAD flag raised")

# ═══ Test 14: workload review — VEH_BOTTLENECK flag ═════════════════════════
# Vehicle at capacity on 4+ days
_v_small = Vehicle("V-SM", "van", ["boiler_service"], 
                   ["Mon", "Tue", "Wed", "Thu", "Fri"], 450, 0.001, 2)
_t_full = Technician("T-FULL", "Full", ["boiler_service"], 43.2, -71.5,
                     ["Mon", "Tue", "Wed", "Thu", "Fri"])
bn_assignments = []
bn_svc = {}
for d in ["Mon", "Tue", "Wed", "Thu"]:
    for i in range(2):
        jid = f"BN-{d}-{i}"
        bn_assignments.append(ScheduleAssignment(jid, "T-FULL", "V-SM", d))
        bn_svc[jid] = 30.0

flags_bn = check_workload(bn_assignments, bn_svc, [_t_full], [_v_small], config)
bn_codes = [f.code for f in flags_bn]
assert "VEH_BOTTLENECK" in bn_codes, f"Expected VEH_BOTTLENECK, got {bn_codes}"
passed += 1
print("  [PASS] Test 14: VEH_BOTTLENECK flag raised")

# ═══ Test 15: end-to-end Phase 1 with example data ══════════════════════════
assignments, exclusions, wk_flags = run_phase1_schedule(
    normal, wd.technicians, wd.vehicles, config, consumed,
)

# Must have produced some assignments
assert len(assignments) > 0, "Phase 1 should assign at least some jobs"

# Every assignment references a valid normal job
normal_ids = {j.job_id for j in normal}
for a in assignments:
    assert a.job_id in normal_ids, f"Assignment {a.job_id} not in normal jobs"
    assert a.tech_id, "tech_id must be set"
    assert a.vehicle_id, "vehicle_id must be set"
    assert a.day, "day must be set"

# Assignments + exclusions should cover all normal jobs
assigned_ids = {a.job_id for a in assignments}
excluded_ids = {e.job_id for e in exclusions}
assert assigned_ids | excluded_ids == normal_ids, (
    f"Not all normal jobs accounted for: "
    f"missing {normal_ids - assigned_ids - excluded_ids}"
)

# No duplicate assignments
assert len(assigned_ids) == len(assignments), "Duplicate job assignments found"

passed += 1
print(f"  [PASS] Test 15: end-to-end Phase 1 — "
      f"{len(assignments)} assigned, {len(exclusions)} excluded, "
      f"{len(wk_flags)} workload flags")

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Phase 1 tests: {passed}/{passed} PASSED")
print(f"{'='*60}")
