"""Full pipeline demo — runs all stages and prints inputs/outputs at each step.

Usage:  .venv/Scripts/python.exe run_demo.py
"""
from __future__ import annotations

from collections import Counter

from nes_dispatch.data import load_weekly_data, validate_inputs
from nes_dispatch.data.models import Exclusion, ReviewFlag
from nes_dispatch.pipeline import (
    apply_exclusion_filters,
    apply_exceptions,
    compute_consumed_capacity,
    plan_special_routes,
    run_phase1_schedule,
    run_phase2_routing,
    run_postprocessing,
    split_special_routes,
)

# ── Config ──────────────────────────────────────────────────────────────────
CONFIG = {
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

SEP = "=" * 72
THIN = "-" * 72


def header(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def sub(title: str) -> None:
    print(f"\n  {THIN}")
    print(f"  {title}")
    print(f"  {THIN}")


def print_exclusions(excl: list[Exclusion], label: str = "Exclusions") -> None:
    if not excl:
        print(f"  {label}: (none)")
        return
    print(f"  {label} ({len(excl)}):")
    for e in excl:
        print(f"    {e.job_id:8s}  {e.reason_code:22s}  {e.detail}")


def print_flags(flags: list[ReviewFlag], label: str = "Review Flags") -> None:
    if not flags:
        print(f"  {label}: (none)")
        return
    print(f"  {label} ({len(flags)}):")
    for f in flags:
        print(f"    [{f.severity:8s}] {f.code:18s}  {f.message}")


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    all_exclusions: list[Exclusion] = []
    all_flags: list[ReviewFlag] = []

    # ── Stage 0: Load ───────────────────────────────────────────────
    header("STAGE 0 — Load & Validate")
    wd = load_weekly_data("data")

    sub("INPUT: Raw data files")
    print(f"  Jobs loaded:       {len(wd.jobs)}")
    print(f"  Technicians:       {len(wd.technicians)}")
    print(f"  Vehicles:          {len(wd.vehicles)}")
    print(f"  Exceptions:        {len(wd.exceptions)}")

    sub("INPUT: Jobs")
    print(f"  {'ID':8s}  {'Area':8s}  {'Type':14s}  Helper  Age  Value    Svc(min)  Address")
    for j in wd.jobs:
        hlp = "YES" if j.helper_needed else "   "
        print(f"  {j.job_id:8s}  {j.area_id:8s}  {j.route_type:14s}  {hlp:6s}  "
              f"{j.age_days:3d}  ${j.value:>7.2f}  {j.service_time_min:5.0f}     {j.address}")

    sub("INPUT: Technicians")
    print(f"  {'ID':6s}  {'Name':18s}  {'Skills':50s}  Home(lat,lon)       Days")
    for t in wd.technicians:
        skills = ", ".join(t.skills)
        days = ", ".join(t.available_days)
        print(f"  {t.tech_id:6s}  {t.name:18s}  {skills:50s}  "
              f"({t.home_lat:.4f},{t.home_lon:.4f})  {days}")

    sub("INPUT: Vehicles")
    print(f"  {'ID':6s}  {'Type':16s}  Cap  Speed  $/m       {'Tags':45s}  Days")
    for v in wd.vehicles:
        tags = ", ".join(v.capability_tags)
        days = ", ".join(v.available_days)
        print(f"  {v.vehicle_id:6s}  {v.vehicle_type:16s}  {v.capacity:3d}  "
              f"{v.speed_mpm:5.0f}  {v.cost_per_metre:.5f}  {tags:45s}  {days}")

    sub("INPUT: Weekly Exceptions")
    print(f"  {'ID':6s}  Scope         Who     Day   Effect         Detail")
    for ex in wd.exceptions:
        print(f"  {ex.exception_id:6s}  {ex.scope_type:12s}  {ex.scope_id:6s}  "
              f"{ex.day:5s} {ex.effect_type:14s}  {ex.effect_value}")

    sub("OUTPUT: Validation")
    errors = validate_inputs(wd, CONFIG)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        return
    print("  All validation checks passed.")

    # ── Stage 1: Exclusion Filters ──────────────────────────────────
    header("STAGE 1 — Exclusion Filters")
    sub("INPUT")
    status_counts = Counter(j.status for j in wd.jobs)
    print(f"  Job statuses: {dict(status_counts)}")

    candidates, excl_s1 = apply_exclusion_filters(wd.jobs)
    all_exclusions.extend(excl_s1)

    sub("OUTPUT")
    print(f"  Candidates passed:  {len(candidates)}")
    print_exclusions(excl_s1)

    # ── Stage 2: Apply Weekly Exceptions ────────────────────────────
    header("STAGE 2 — Apply Weekly Exceptions")
    sub("INPUT: availability BEFORE exceptions")
    for t in wd.technicians:
        print(f"  Tech {t.tech_id}: {', '.join(t.available_days)}")
    for v in wd.vehicles:
        print(f"  Veh  {v.vehicle_id}: {', '.join(v.available_days)}")

    apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)

    sub("OUTPUT: availability AFTER exceptions")
    for t in wd.technicians:
        print(f"  Tech {t.tech_id}: {', '.join(t.available_days)}")
    for v in wd.vehicles:
        print(f"  Veh  {v.vehicle_id}: {', '.join(v.available_days)}")

    # ── Stage 3: Reserve Special Routes ─────────────────────────────
    header("STAGE 3 — Reserve Special Routes")
    special, normal = split_special_routes(candidates)

    sub("INPUT: candidate split")
    print(f"  Special jobs ({len(special)}):")
    for j in special:
        hlp = " [HELPER]" if j.helper_needed else ""
        print(f"    {j.job_id}  type={j.route_type}{hlp}  {j.address}")
    print(f"  Normal jobs:  {len(normal)}")

    sp_assign, sp_excl = plan_special_routes(special, wd.technicians, wd.vehicles, CONFIG)
    all_exclusions.extend(sp_excl)

    sub("OUTPUT: special assignments")
    if sp_assign:
        print(f"  {'Job':8s}  {'Tech':6s}  {'Vehicle':8s}  Day    Helper")
        for a in sp_assign:
            hlp = a.helper_tech_id or "-"
            print(f"  {a.job_id:8s}  {a.tech_id:6s}  {a.vehicle_id:8s}  "
                  f"{a.day:5s}  {hlp}")
    else:
        print("  (none)")
    print_exclusions(sp_excl, "Special-route exclusions")

    # ── Stage 4: Phase 1 — Score & Schedule ─────────────────────────
    header("STAGE 4 — Phase 1: Score & Schedule")
    jobs_lookup = {j.job_id: j for j in wd.jobs}
    consumed = compute_consumed_capacity(sp_assign, jobs_lookup)

    sub("INPUT")
    print(f"  Normal jobs to schedule: {len(normal)}")
    print(f"  Consumed capacity from specials:")
    print(f"    stop_count:   {dict(consumed['stop_count'])}")
    print(f"    service_mins: {dict(consumed['service_mins'])}")

    ph1_assign, ph1_excl, wk_flags = run_phase1_schedule(
        normal, wd.technicians, wd.vehicles, CONFIG, consumed,
    )
    all_exclusions.extend(ph1_excl)
    all_flags.extend(wk_flags)

    sub("OUTPUT: Phase 1 assignments")
    print(f"  Assigned: {len(ph1_assign)} jobs")
    print(f"  {'Job':8s}  {'Tech':6s}  {'Vehicle':8s}  Day    Helper  Description")
    for a in sorted(ph1_assign, key=lambda x: (x.day, x.tech_id)):
        hlp = a.helper_tech_id or "-"
        desc = jobs_lookup[a.job_id].description[:40]
        print(f"  {a.job_id:8s}  {a.tech_id:6s}  {a.vehicle_id:8s}  "
              f"{a.day:5s}  {hlp:6s}  {desc}")
    print_exclusions(ph1_excl, "Phase 1 exclusions")
    print_flags(wk_flags, "Workload flags")

    # ── Stage 5: Phase 2 — Order Stops ──────────────────────────────
    header("STAGE 5 — Phase 2: Order Stops (Nearest-Neighbour Routing)")
    all_assign = sp_assign + ph1_assign

    sub("INPUT")
    # Group by route key for display
    from collections import defaultdict
    bundles: dict[tuple, list] = defaultdict(list)
    for a in all_assign:
        bundles[(a.tech_id, a.vehicle_id, a.day)].append(a.job_id)
    print(f"  Route bundles to sequence: {len(bundles)}")
    for (tid, vid, day), jids in sorted(bundles.items()):
        print(f"    {tid}/{vid}/{day}: {', '.join(jids)}")

    routes, ph2_excl, ph2_flags = run_phase2_routing(
        all_assign, wd.technicians, wd.vehicles, jobs_lookup, CONFIG,
    )
    all_exclusions.extend(ph2_excl)
    all_flags.extend(ph2_flags)

    sub("OUTPUT: Routes")
    print(f"  {'Tech':6s}  {'Vehicle':8s}  Day    Stops  Dist(km)  Time(min)  Sequence")
    for r in sorted(routes, key=lambda x: (x.day, x.tech_id)):
        seq = " → ".join(r.visited_job_ids) if r.visited_job_ids else "(empty)"
        print(f"  {r.tech_id:6s}  {r.vehicle_id:8s}  {r.day:5s}  "
              f"{len(r.visited_job_ids):5d}  {r.total_distance_m/1000:8.1f}  "
              f"{r.total_time_min:9.1f}  {seq}")
        if r.dropped_job_ids:
            print(f"         DROPPED: {', '.join(r.dropped_job_ids)}")
    print_exclusions(ph2_excl, "Phase 2 exclusions (ROUTE_DROP)")
    print_flags(ph2_flags, "Phase 2 flags")

    # ── Stage 6: Post-processing ────────────────────────────────────
    header("STAGE 6 — Post-processing")

    sub("INPUT")
    visited_ids = set()
    for r in routes:
        visited_ids.update(r.visited_job_ids)
    unassigned = [j for j in candidates if j.job_id not in visited_ids]
    print(f"  Total candidates:  {len(candidates)}")
    print(f"  Visited (routed):  {len(visited_ids)}")
    print(f"  Unassigned:        {len(unassigned)}")
    if unassigned:
        print(f"  Unassigned jobs:   {', '.join(j.job_id for j in unassigned)}")

    standby, readiness, pp_flags = run_postprocessing(
        routes, candidates, all_assign, wd.technicians, wd.vehicles, CONFIG,
    )
    all_flags.extend(pp_flags)

    sub("OUTPUT: Standby Rankings")
    for key in sorted(standby.keys()):
        tid, vid, day = key
        slist = standby[key]
        candidates_str = ", ".join(slist[:5])
        if len(slist) > 5:
            candidates_str += f" ... (+{len(slist)-5} more)"
        print(f"  {tid}/{vid}/{day}: {len(slist)} candidates"
              f"{' — ' + candidates_str if slist else ''}")

    sub("OUTPUT: Area Readiness")
    print(f"  {'Area':10s}  Level")
    for area in sorted(readiness.keys()):
        level = readiness[area]
        indicator = {"Good": "+++", "Moderate": " + ", "Lean": " - "}[level]
        print(f"  {area:10s}  {level:10s}  {indicator}")

    sub("OUTPUT: Post-processing Flags")
    print_flags(pp_flags)

    # ── Final Summary ───────────────────────────────────────────────
    header("FINAL SUMMARY")

    sub("All Review Flags (merged)")
    print_flags(all_flags)
    severity_counts = Counter(f.severity for f in all_flags)
    print(f"\n  Totals: {dict(severity_counts)}")

    sub("All Exclusions")
    print_exclusions(all_exclusions)
    reason_counts = Counter(e.reason_code for e in all_exclusions)
    print(f"\n  By reason code:")
    for code, count in sorted(reason_counts.items()):
        print(f"    {code:22s}  {count}")

    sub("Pipeline Totals")
    total_visited = sum(len(r.visited_job_ids) for r in routes)
    total_dropped = sum(len(r.dropped_job_ids) for r in routes)
    total_dist = sum(r.total_distance_m for r in routes) / 1000
    total_time = sum(r.total_time_min for r in routes)
    print(f"  Input jobs:         {len(wd.jobs)}")
    print(f"  Candidates:         {len(candidates)}")
    print(f"  Assigned & routed:  {total_visited}")
    print(f"  Dropped (Phase 2):  {total_dropped}")
    print(f"  Excluded:           {len(all_exclusions)}")
    print(f"  Routes produced:    {len(routes)}")
    print(f"  Total distance:     {total_dist:.1f} km")
    print(f"  Total time:         {total_time:.0f} min ({total_time/60:.1f} hrs)")
    print(f"  Review flags:       {len(all_flags)}")
    areas_good = sum(1 for v in readiness.values() if v == "Good")
    areas_mod = sum(1 for v in readiness.values() if v == "Moderate")
    areas_lean = sum(1 for v in readiness.values() if v == "Lean")
    print(f"  Area readiness:     {areas_good} Good, {areas_mod} Moderate, {areas_lean} Lean")

    # ── Stage 7: Route Maps ─────────────────────────────────────────
    header("STAGE 7 — Route Maps (osmnx)")
    print("  Drawing road-network maps for each route...")
    try:
        from nes_dispatch.mapping import draw_all_routes

        draw_all_routes(
            routes, wd.technicians, jobs_lookup,
            show=True,
        )
    except Exception as exc:
        print(f"  Map drawing failed: {exc}")
        print("  (Requires internet for initial OSM download.)")


if __name__ == "__main__":
    main()
