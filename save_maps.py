"""Save route maps as PNG files to output/maps/."""
from nes_dispatch.data import load_weekly_data
from nes_dispatch.pipeline import (
    apply_exclusion_filters, apply_exceptions, split_special_routes,
    plan_special_routes, compute_consumed_capacity, run_phase1_schedule,
    run_phase2_routing,
)
from nes_dispatch.mapping import draw_all_routes

CONFIG = {
    "T_max_minutes": 480, "T_max_phase1_fraction": 0.80, "P_max_stops": 14,
    "R_cluster_radius_m": 30000, "r_interstop_limit_m": 15000,
    "seasonal_weights": {
        "summer": {"w_g": 0.4, "w_f": 0.2, "w_a": 0.3, "w_r": 0.1},
        "winter": {"w_g": 0.2, "w_f": 0.4, "w_a": 0.3, "w_r": 0.1},
    },
    "summer_months": [3, 4, 5, 6, 7, 8, 9],
    "tech_overload_pct": 0.90, "veh_bottleneck_days": 4,
    "weak_standby_threshold": 2,
    "lat_bounds": [41.0, 48.0], "lon_bounds": [-74.0, -67.0],
}

wd = load_weekly_data("data")
cands, _ = apply_exclusion_filters(wd.jobs)
apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)
sp, norm = split_special_routes(cands)
sp_a, _ = plan_special_routes(sp, wd.technicians, wd.vehicles, CONFIG)
consumed = compute_consumed_capacity(sp_a, {j.job_id: j for j in wd.jobs})
ph1, _, _ = run_phase1_schedule(norm, wd.technicians, wd.vehicles, CONFIG, consumed)
jl = {j.job_id: j for j in wd.jobs}
routes, _, _ = run_phase2_routing(sp_a + ph1, wd.technicians, wd.vehicles, jl, CONFIG)
print(f"{len(routes)} routes ready")

draw_all_routes(routes, wd.technicians, jl, save_dir="output/maps")
print("Done — PNGs saved to output/maps/")
