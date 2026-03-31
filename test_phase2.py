"""Tests for pipeline Stage 6: Phase 2 — Order Stops.

Covers:
  - Haversine distance correctness
  - Travel time computation
  - Nearest-neighbour ordering
  - Feasibility: time-budget drop
  - Feasibility: capacity drop
  - CROSS_AREA flag on large inter-stop gaps
  - NO_FEASIBLE flag when all jobs dropped
  - Re-run NN after drops
  - End-to-end Phase 2 with example data (piped from Phase 1)
"""

import math
from nes_dispatch.data import load_weekly_data
from nes_dispatch.data.models import (
    Exclusion, Job, ReviewFlag, RouteResult,
    ScheduleAssignment, Technician, Vehicle,
)
from nes_dispatch.routing.distance import haversine_m, travel_time_min
from nes_dispatch.routing.nearest_neighbour import build_route, _nn_order, _walk_route
from nes_dispatch.pipeline import (
    apply_exclusion_filters,
    apply_exceptions,
    compute_consumed_capacity,
    run_phase1_schedule,
    run_phase2_routing,
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
_tech = Technician("T-A", "Alice", ["boiler_service"], 43.20, -71.50, ["Mon"])
_veh = Vehicle("V-A", "van", ["boiler_service"], ["Mon"], 450.0, 0.001, 10)

def _job(jid, lat, lon, svc=45.0):
    hrs = svc / 60.0 if svc else 1.0
    # Use a required-hours category so planned_hours respects the svc param
    return Job(
        job_id=jid, address="addr", city="TestCity", state="RI",
        area_id="A-1", area_name="A-1",
        job_category="Vent / Trap / Repair / Piping Work",
        queue="Normal jobs", latitude=lat, longitude=lon,
        created_date="2026-03-01", age_days=10, required_job_hours=hrs,
    )

passed = 0

# ═══ Test 1: haversine known distance ═══════════════════════════════════════
# Concord NH (43.208, -71.538) to Manchester NH (42.991, -71.464) ≈ 24.5 km
d = haversine_m(43.208, -71.538, 42.991, -71.464)
assert 24_000 < d < 25_000, f"Expected ~24.5 km, got {d/1000:.1f} km"
passed += 1
print(f"  [PASS] Test 1: haversine Concord→Manchester = {d/1000:.1f} km")

# ═══ Test 2: travel_time_min ════════════════════════════════════════════════
t = travel_time_min(9000, 450)  # 9 km at 450 m/min = 20 min
assert abs(t - 20.0) < 0.01, f"Expected 20 min, got {t}"
assert travel_time_min(1000, 0) == float("inf")
passed += 1
print(f"  [PASS] Test 2: travel_time_min = {t:.1f} min")

# ═══ Test 3: NN ordering — closest-first ════════════════════════════════════
j1 = _job("J1", 43.21, -71.51)   # very close to depot
j2 = _job("J2", 43.25, -71.55)   # farther
j3 = _job("J3", 43.22, -71.52)   # middle

ordered = _nn_order(43.20, -71.50, [j2, j3, j1])
ids = [j.job_id for j in ordered]
assert ids[0] == "J1", f"First should be J1 (closest), got {ids[0]}"
assert ids[1] == "J3", f"Second should be J3, got {ids[1]}"
assert ids[2] == "J2", f"Third should be J2, got {ids[2]}"
passed += 1
print(f"  [PASS] Test 3: NN ordering = {ids}")

# ═══ Test 4: feasibility — all jobs fit ═════════════════════════════════════
jobs_close = [_job(f"FC-{i}", 43.20 + i*0.005, -71.50) for i in range(3)]
route, dropped, flags = build_route(_tech, _veh, "Mon", jobs_close, config)
assert len(route.visited_job_ids) == 3
assert len(dropped) == 0
assert route.total_distance_m > 0
assert route.total_time_min > 0
assert route.method == "nearest_neighbour"
passed += 1
print(f"  [PASS] Test 4: 3 close jobs all visited, dist={route.total_distance_m/1000:.1f} km, "
      f"time={route.total_time_min:.1f} min")

# ═══ Test 5: feasibility — time-budget drop ═════════════════════════════════
# Jobs with very long service time should cause drops
jobs_long = [_job(f"TL-{i}", 43.20 + i*0.01, -71.50, svc=200.0) for i in range(5)]
route_tl, dropped_tl, flags_tl = build_route(_tech, _veh, "Mon", jobs_long, config)
assert len(dropped_tl) > 0, "Some jobs should be dropped (time budget)"
assert len(route_tl.visited_job_ids) + len(route_tl.dropped_job_ids) == 5
drop_flags = [f for f in flags_tl if f.code == "ROUTE_DROP"]
assert len(drop_flags) == len(dropped_tl)
passed += 1
print(f"  [PASS] Test 5: time-budget drop — visited={len(route_tl.visited_job_ids)}, "
      f"dropped={len(dropped_tl)}")

# ═══ Test 6: feasibility — capacity drop ════════════════════════════════════
_veh_small = Vehicle("V-SM", "van", ["boiler_service"], ["Mon"], 450.0, 0.001, 3)
jobs_many = [_job(f"CP-{i}", 43.20 + i*0.002, -71.50, svc=10.0) for i in range(6)]
route_cp, dropped_cp, _ = build_route(_tech, _veh_small, "Mon", jobs_many, config)
# Vehicle capacity = 3, P_max = 14 → min = 3
assert len(route_cp.visited_job_ids) <= 3, f"Visited {len(route_cp.visited_job_ids)} > cap 3"
assert len(dropped_cp) >= 3
passed += 1
print(f"  [PASS] Test 6: capacity drop — visited={len(route_cp.visited_job_ids)}, "
      f"dropped={len(dropped_cp)}")

# ═══ Test 7: CROSS_AREA flag on large inter-stop gap ═══════════════════════
# Place two jobs far apart (>15 km gap)
j_near = _job("CA-1", 43.21, -71.51, svc=10.0)
j_far = _job("CA-2", 43.40, -71.30, svc=10.0)  # ~25 km away from CA-1
route_ca, _, flags_ca = build_route(_tech, _veh, "Mon", [j_near, j_far], config)
cross_flags = [f for f in flags_ca if f.code == "CROSS_AREA"]
assert len(cross_flags) >= 1, f"Expected CROSS_AREA flag, got codes {[f.code for f in flags_ca]}"
passed += 1
print(f"  [PASS] Test 7: CROSS_AREA flag raised for {cross_flags[0].refs.get('cross_area_jobs')}")

# ═══ Test 8: NO_FEASIBLE when all jobs dropped ═════════════════════════════
# Extremely slow vehicle → cannot even reach first job and return
_veh_slow = Vehicle("V-SL", "van", ["boiler_service"], ["Mon"], 1.0, 0.001, 10)
j_unreachable = _job("NF-1", 43.50, -71.50, svc=400.0)
route_nf, dropped_nf, flags_nf = build_route(_tech, _veh_slow, "Mon",
                                              [j_unreachable], config)
nf_flags = [f for f in flags_nf if f.code == "NO_FEASIBLE"]
assert len(nf_flags) == 1, f"Expected NO_FEASIBLE, got {[f.code for f in flags_nf]}"
assert len(route_nf.visited_job_ids) == 0
passed += 1
print(f"  [PASS] Test 8: NO_FEASIBLE flag raised when all jobs infeasible")

# ═══ Test 9: empty bundle produces empty route ═════════════════════════════
route_empty, _, flags_empty = build_route(_tech, _veh, "Mon", [], config)
assert route_empty.visited_job_ids == []
assert route_empty.total_distance_m == 0.0
assert flags_empty == []
passed += 1
print("  [PASS] Test 9: empty bundle → empty route, no flags")

# ═══ Test 10: end-to-end Phase 2 with example data ═════════════════════════
wd = load_weekly_data("data")
candidates, _ = apply_exclusion_filters(wd.jobs)
apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)
special, normal = split_special_routes(candidates)
sp_asgn, sp_excl = plan_special_routes(special, wd.technicians, wd.vehicles, config)
jobs_map = {j.job_id: j for j in wd.jobs}
consumed = compute_consumed_capacity(sp_asgn, jobs_map)

p1_asgn, p1_excl, wk_flags = run_phase1_schedule(
    normal, wd.technicians, wd.vehicles, config, consumed,
)

# Merge special + phase1 assignments for Phase 2
all_assignments = sp_asgn + p1_asgn

routes, p2_excl, p2_flags = run_phase2_routing(
    all_assignments, wd.technicians, wd.vehicles, jobs_map, config,
)

assert len(routes) > 0, "Phase 2 should produce at least one route"

total_visited = sum(len(r.visited_job_ids) for r in routes)
total_dropped = sum(len(r.dropped_job_ids) for r in routes)
total_assigned = len(all_assignments)

# Every assigned job should appear in exactly one route (visited or dropped)
all_route_jobs = set()
for r in routes:
    for jid in r.visited_job_ids + r.dropped_job_ids:
        assert jid not in all_route_jobs, f"Job {jid} in multiple routes"
        all_route_jobs.add(jid)
assigned_ids = {a.job_id for a in all_assignments}
assert all_route_jobs == assigned_ids, (
    f"Route jobs != assigned jobs: "
    f"missing={assigned_ids - all_route_jobs}, extra={all_route_jobs - assigned_ids}"
)

# All routes have valid structure
for r in routes:
    assert r.tech_id, "tech_id missing"
    assert r.vehicle_id, "vehicle_id missing"
    assert r.day, "day missing"
    assert r.total_time_min >= 0
    assert r.total_distance_m >= 0
    assert r.method == "nearest_neighbour"

passed += 1
print(f"  [PASS] Test 10: end-to-end Phase 2 — {len(routes)} routes, "
      f"{total_visited} visited, {total_dropped} dropped, "
      f"{len(p2_flags)} flags")

# Print route summary
for r in routes:
    print(f"    {r.tech_id}/{r.vehicle_id}/{r.day}: "
          f"{len(r.visited_job_ids)} stops, "
          f"{r.total_distance_m/1000:.1f} km, "
          f"{r.total_time_min:.0f} min"
          + (f" (dropped {len(r.dropped_job_ids)})" if r.dropped_job_ids else ""))

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Phase 2 tests: {passed}/{passed} PASSED")
print(f"{'='*60}")
