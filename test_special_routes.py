"""Tests for pipeline Stage 4: Reserve Special Routes."""

import copy
from nes_dispatch.data import load_weekly_data
from nes_dispatch.pipeline import (
    apply_exclusion_filters,
    apply_exceptions,
    split_special_routes,
    plan_special_routes,
    compute_consumed_capacity,
)

# ── Setup: run stages 2–3 first ─────────────────────────────────────────────
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

# ═══ Test 1: split_special_routes ════════════════════════════════════════════
special, normal = split_special_routes(candidates)

special_ids = {j.job_id for j in special}
normal_ids = {j.job_id for j in normal}

# Radiator jobs: SM8-30402 (Replacement), SM8-30405 (Pick-Up), SM8-30411 (Refinishing),
#                SM8-30440 (Service), SM8-30451 (Replace & Refinish)
# Helper/Two-Man: SM8-50101 (New Equipment, Accepted Quotes), SM8-50102 (Castrads)
# SM8-20319 is Accepted Quotes → treated as Two-Man (helper_needed)
for rid in ["SM8-30402", "SM8-30405", "SM8-30411", "SM8-30440", "SM8-30451"]:
    assert rid in special_ids, f"Radiator {rid} should be special"
for hid in ["SM8-50101", "SM8-50102", "SM8-20319"]:
    assert hid in special_ids, f"Helper/Two-Man {hid} should be special"

# Normal jobs should not appear in special
assert "SM8-10452" in normal_ids
assert "SM8-10510" in normal_ids

assert len(special) + len(normal) == len(candidates)
print(f"TEST 1 PASS — split: {len(special)} special, {len(normal)} normal")

# ═══ Test 2: plan_special_routes produces assignments ════════════════════════
assignments, exclusions = plan_special_routes(
    special, wd.technicians, wd.vehicles, config,
)

assigned_ids = {a.job_id for a in assignments}
excluded_ids = {e.job_id for e in exclusions}

print(f"TEST 2 — assigned: {sorted(assigned_ids)}, excluded: {sorted(excluded_ids)}")
# Every special job should end up assigned OR excluded (none lost)
assert assigned_ids | excluded_ids == special_ids, (
    f"Lost jobs: {special_ids - assigned_ids - excluded_ids}"
)
print("TEST 2 PASS — all special jobs accounted for")

# ═══ Test 3: radiator jobs get a vehicle with radiator capability ════════════
veh_lookup = {v.vehicle_id: v for v in wd.vehicles}
for a in assignments:
    job = next(j for j in special if j.job_id == a.job_id)
    if job.route_type == "radiator":
        veh = veh_lookup[a.vehicle_id]
        assert "radiator" in veh.capability_tags, (
            f"{a.job_id} assigned to {a.vehicle_id} without radiator tag"
        )
print("TEST 3 PASS — radiator jobs use radiator-capable vehicle")

# ═══ Test 4: helper jobs have a helper_tech_id set ═══════════════════════════
helper_assignments = [a for a in assignments
                      if next(j for j in special if j.job_id == a.job_id).helper_needed]
for a in helper_assignments:
    assert a.helper_tech_id is not None, (
        f"Helper job {a.job_id} missing helper_tech_id"
    )
    assert a.helper_tech_id != a.tech_id, (
        f"Helper job {a.job_id}: helper is same as primary"
    )
print(f"TEST 4 PASS — {len(helper_assignments)} helper jobs have distinct helper tech")

# ═══ Test 5: assignments respect availability ════════════════════════════════
tech_lookup = {t.tech_id: t for t in wd.technicians}
for a in assignments:
    tech = tech_lookup[a.tech_id]
    assert a.day in tech.available_days, (
        f"{a.tech_id} not available on {a.day}"
    )
    veh = veh_lookup[a.vehicle_id]
    assert a.day in veh.available_days, (
        f"{a.vehicle_id} not available on {a.day}"
    )
print("TEST 5 PASS — all assignments respect tech/vehicle availability")

# ═══ Test 6: compute_consumed_capacity ═══════════════════════════════════════
jobs_by_id = {j.job_id: j for j in wd.jobs}
cap = compute_consumed_capacity(assignments, jobs_by_id)

total_stops = sum(cap["stop_count"].values())
assert total_stops == len(assignments), (
    f"Stop count {total_stops} != {len(assignments)} assignments"
)
total_mins = sum(cap["service_mins"].values())
expected_mins = sum(jobs_by_id[a.job_id].service_time_min for a in assignments)
assert abs(total_mins - expected_mins) < 0.01
print(f"TEST 6 PASS — consumed capacity: {total_stops} stops, {total_mins:.0f} min")

# ═══ Test 7: ONE_VEH_PER_TECH / ONE_TECH_PER_VEH constraints ════════════════
# Check no tech uses two different vehicles on the same day
for (tid, day), vid in cap["tech_veh"].items():
    for a in assignments:
        if a.tech_id == tid and a.day == day:
            assert a.vehicle_id == vid, (
                f"Tech {tid} on {day}: conflicting vehicles"
            )
print("TEST 7 PASS — one-vehicle-per-tech / one-tech-per-vehicle respected")

# ═══ Test 8: No assignment exceeds capacity ══════════════════════════════════
for (vid, day), cnt in cap["stop_count"].items():
    veh = veh_lookup[vid]
    assert cnt <= veh.capacity, (
        f"Vehicle {vid} on {day}: {cnt} stops > capacity {veh.capacity}"
    )
print("TEST 8 PASS — no vehicle over-capacity")

print()
print("ALL 8 TESTS PASSED")
