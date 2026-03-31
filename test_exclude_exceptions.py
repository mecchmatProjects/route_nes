"""Tests for pipeline stages 2–3: exclusion filters + apply exceptions."""

import copy
from nes_dispatch.data import load_weekly_data
from nes_dispatch.pipeline import apply_exclusion_filters, apply_exceptions

wd = load_weekly_data("data")

# ═══ Stage 2: apply_exclusion_filters ════════════════════════════════════════

# Test 1: all example jobs have eligible queues → none excluded
candidates, exclusions = apply_exclusion_filters(wd.jobs)
assert len(candidates) == 25
assert len(exclusions) == 0
print("TEST 1 PASS — all candidates pass (no Urgent/On Hold queues)")

# Test 2: set some jobs to excluded queues (Urgent, On Hold)
wd2 = copy.deepcopy(wd)
wd2.jobs[0].queue = "Urgent"
wd2.jobs[1].queue = "On Hold"
cands, excls = apply_exclusion_filters(wd2.jobs)
assert len(cands) == 23
assert len(excls) == 2
codes = {e.reason_code for e in excls}
assert "QUEUE_URGENT" in codes
assert "QUEUE_ON_HOLD" in codes
print("TEST 2 PASS — Urgent/On Hold correctly filtered")

# Test 3: verify correct reason codes
for e in excls:
    if e.job_id == wd2.jobs[0].job_id:
        assert e.reason_code == "QUEUE_URGENT"
    elif e.job_id == wd2.jobs[1].job_id:
        assert e.reason_code == "QUEUE_ON_HOLD"
print("TEST 3 PASS — reason codes match queue")

# ═══ Stage 3: apply_exceptions ═══════════════════════════════════════════════
# Example exceptions CSV: Chris blocked Friday (PTO), Dave blocked Monday (Training)
# Tech mapping: T-01=Mike, T-02=Chris, T-03=Dave

# Test 4: before exceptions, Mike (T-01) has all 5 days; no exception for him
wd3 = copy.deepcopy(wd)
t01_before = next(t for t in wd3.technicians if t.tech_id == "T-01")
assert set(t01_before.available_days) == {"Mon", "Tue", "Wed", "Thu", "Fri"}
apply_exceptions(wd3.technicians, wd3.vehicles, wd3.exceptions)
t01_after = next(t for t in wd3.technicians if t.tech_id == "T-01")
assert set(t01_after.available_days) == {"Mon", "Tue", "Wed", "Thu", "Fri"}
print("TEST 4 PASS — Mike (T-01) unaffected by exceptions")

# Test 5: Chris (T-02) Friday blocked → Fri removed
t02 = next(t for t in wd3.technicians if t.tech_id == "T-02")
assert "Fri" not in t02.available_days, f"Expected Fri removed, got {t02.available_days}"
assert "Mon" in t02.available_days
print("TEST 5 PASS — Chris (T-02) Fri removed (PTO)")

# Test 6: Dave (T-03) Monday blocked → Mon removed
t03_after = next(t for t in wd3.technicians if t.tech_id == "T-03")
assert "Mon" not in t03_after.available_days, f"Expected Mon removed, got {t03_after.available_days}"
assert "Tue" in t03_after.available_days
print("TEST 6 PASS — Dave (T-03) Mon removed (Training)")

# Test 7: vehicles not mentioned in exceptions are untouched
for v in wd3.vehicles:
    assert len(v.available_days) == 5, f"Vehicle {v.vehicle_id} days changed unexpectedly"
print("TEST 7 PASS — all vehicles unaffected (no vehicle exceptions in data)")

# Test 8: combined pipeline order (exclude then apply exceptions)
wd4 = copy.deepcopy(wd)
wd4.jobs[0].queue = "Urgent"
cands4, excls4 = apply_exclusion_filters(wd4.jobs)
assert len(cands4) == 24
apply_exceptions(wd4.technicians, wd4.vehicles, wd4.exceptions)
t02_4 = next(t for t in wd4.technicians if t.tech_id == "T-02")
assert "Fri" not in t02_4.available_days
print("TEST 8 PASS — exclude then apply_exceptions works in sequence")

print()
print("ALL 8 TESTS PASSED")
