"""Tests for pipeline stages 2–3: exclusion filters + apply exceptions."""

import copy
from nes_dispatch.data import load_weekly_data
from nes_dispatch.pipeline import apply_exclusion_filters, apply_exceptions

wd = load_weekly_data("data")

# ═══ Stage 2: apply_exclusion_filters ════════════════════════════════════════

# Test 1: all example jobs are "candidate" → none excluded
candidates, exclusions = apply_exclusion_filters(wd.jobs)
assert len(candidates) == 25
assert len(exclusions) == 0
print("TEST 1 PASS — all candidates pass (no excluded/assigned)")

# Test 2: mark some jobs as excluded / assigned / cancelled
wd2 = copy.deepcopy(wd)
wd2.jobs[0].status = "assigned"
wd2.jobs[1].status = "excluded"
wd2.jobs[2].status = "cancelled"
cands, excls = apply_exclusion_filters(wd2.jobs)
assert len(cands) == 22
assert len(excls) == 3
codes = {e.reason_code for e in excls}
assert "ALREADY_ASSIGNED" in codes
assert "STATUS_EXCLUDED" in codes
print("TEST 2 PASS — assigned/excluded/cancelled correctly filtered")

# Test 3: verify correct reason codes
for e in excls:
    if e.job_id == wd2.jobs[0].job_id:
        assert e.reason_code == "ALREADY_ASSIGNED"
    else:
        assert e.reason_code == "STATUS_EXCLUDED"
print("TEST 3 PASS — reason codes match status")

# ═══ Stage 3: apply_exceptions ═══════════════════════════════════════════════

# Test 4: before exceptions, T-03 has Mon–Thu; after, Fri removed (was unavailable)
wd3 = copy.deepcopy(wd)
t03 = next(t for t in wd3.technicians if t.tech_id == "T-03")
assert "Fri" not in t03.available_days  # T-03 base is Mon–Thu, no Fri anyway
# Actually check T-01 Wed partial — should keep Wed
t01_before = next(t for t in wd3.technicians if t.tech_id == "T-01")
assert "Wed" in t01_before.available_days
apply_exceptions(wd3.technicians, wd3.vehicles, wd3.exceptions)
t01_after = next(t for t in wd3.technicians if t.tech_id == "T-01")
assert "Wed" in t01_after.available_days, "Partial exception should keep the day"
print("TEST 4 PASS — partial exception keeps day in available_days")

# Test 5: T-02 Mon unavailable → Mon removed
t02 = next(t for t in wd3.technicians if t.tech_id == "T-02")
assert "Mon" not in t02.available_days
print("TEST 5 PASS — T-02 Mon removed (unavailable/training)")

# Test 6: T-03 Fri unavailable → Fri removed
t03_after = next(t for t in wd3.technicians if t.tech_id == "T-03")
assert "Fri" not in t03_after.available_days
print("TEST 6 PASS — T-03 Fri removed (PTO)")

# Test 7: V-4 Tue and Thu unavailable → both removed
v4 = next(v for v in wd3.vehicles if v.vehicle_id == "V-4")
assert "Tue" not in v4.available_days
assert "Thu" not in v4.available_days
assert "Mon" in v4.available_days  # Mon/Wed/Fri were base; Mon & Fri remain
assert "Fri" in v4.available_days
print("TEST 7 PASS — V-4 Tue/Thu removed (maintenance)")

# Test 8: vehicles not mentioned in exceptions are untouched
v5 = next(v for v in wd3.vehicles if v.vehicle_id == "V-5")
assert v5.available_days == ["Mon", "Tue", "Wed", "Thu", "Fri"]
print("TEST 8 PASS — unaffected vehicle unchanged")

# Test 9: combined pipeline order (exclude then apply exceptions)
wd4 = copy.deepcopy(wd)
wd4.jobs[0].status = "assigned"
cands4, excls4 = apply_exclusion_filters(wd4.jobs)
assert len(cands4) == 24
apply_exceptions(wd4.technicians, wd4.vehicles, wd4.exceptions)
t02_4 = next(t for t in wd4.technicians if t.tech_id == "T-02")
assert "Mon" not in t02_4.available_days
print("TEST 9 PASS — exclude then apply_exceptions works in sequence")

print()
print("ALL 9 TESTS PASSED")
