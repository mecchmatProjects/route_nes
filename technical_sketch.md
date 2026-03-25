# Technical Sketch — NES Two-Layer Weekly Dispatch Engine

> Companion to `main.tex`. This document provides implementation-level detail:
> module outline, data schemas, pseudocode, rule-evaluation pipeline, config
> schema, and the weekly-run flow diagram.

---

## 1. Design Goal

Deliver a **deterministic, auditable** Python engine that:

1. Accepts structured weekly data (jobs, technicians, vehicles, exceptions).
2. Runs a two-layer optimisation pipeline (Layer 1 = scheduling, Layer 2 = routing).
3. Produces reviewable route proposals, review flags, and exclusion reports — never auto-books.
4. Is independently testable (no UI, no database, pure function pipeline).

---

## 2. Module Outline

```text
nes_dispatch/
│
├── __init__.py
│
├── data/
│   ├── loaders.py            # CSV / Airtable readers → dataclasses
│   ├── models.py             # Job, Technician, Vehicle, WeeklyException, WeeklyData
│   └── validators.py         # Pre-run sanity checks (schema, coordinates, refs)
│
├── scheduling/               # ── Layer 1 ──
│   ├── eligibility.py        # Build e[j,t,k,d] and e_H[j,t,d] matrices
│   ├── milp.py               # Pyomo Layer-1 MILP  (solve_scheduling)
│   └── greedy.py             # Greedy fallback scheduler
│
├── routing/                  # ── Layer 2 ──
│   ├── clustering.py         # Geographic cluster construction (Algorithm 1)
│   ├── distance.py           # OSMnx / Haversine distance-matrix builder
│   ├── milp.py               # Pyomo Layer-2 routing MILP (MTZ)
│   ├── sa.py                 # Simulated Annealing solver
│   ├── greedy.py             # Constructive greedy heuristic
│   └── bfs.py                # Brute-force / branch-and-bound
│
├── postprocess/
│   ├── standby.py            # Standby job ranking
│   ├── readiness.py          # Area readiness computation (Good / Moderate / Lean)
│   ├── flags.py              # Review-flag and exclusion-report generation
│   └── output.py             # Route maps, text summaries, JSON artefacts
│
├── config.py                 # Loads JSON/YAML config; merges Airtable overrides
└── pipeline.py               # Top-level orchestrator (the 9-step weekly pipeline)
```

### Key conventions

| Convention | Detail |
|---|---|
| **Pure functions** | Every stage is `f(inputs, config) → outputs`. No global state. |
| **Solver-agnostic** | `scheduling/milp.py` and `routing/milp.py` share the same `solve(data, config) → Result` signature. Falls back to greedy if Pyomo/CBC unavailable. |
| **Idempotent** | Same inputs + config + seed → identical outputs. SA seeds live in config. |
| **I/O at the edges** | Only `loaders.py` and `output.py` touch the filesystem or network. |

---

## 3. Schema Sketch

All domain objects are Python `@dataclass` instances defined in `data/models.py`.

### Job

```python
@dataclass
class Job:
    job_id: str
    address: str
    latitude: float              # WGS-84
    longitude: float             # WGS-84
    area_id: str                 # ∈ A
    route_type: str              # "normal" | "radiator" | "nh_overnight" | "helper"
    helper_needed: bool          # h_j — True if two-man job
    age_days: int                # α_j — days since creation
    value: float                 # w_j — base revenue ($)
    service_time_min: float      # τ_j — on-site duration (minutes)
    status: str                  # "candidate" | "excluded" | "assigned"
    description: str = ""
```

### Technician

```python
@dataclass
class Technician:
    tech_id: str
    name: str
    skills: list[str]            # skill_t
    home_lat: float              # y_t
    home_lon: float              # x_t
    available_days: list[str]    # D_t (before exceptions)
```

### Vehicle

```python
@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str
    capability_tags: list[str]   # cap_k
    available_days: list[str]    # D_k (before exceptions)
    speed_mpm: float             # v_k (metres per minute)
    cost_per_metre: float        # c_k ($/m)
    capacity: int                # Q_k (max stops per route)
```

### WeeklyException

```python
@dataclass
class WeeklyException:
    exception_id: str
    scope_type: str              # "technician" | "vehicle"
    scope_id: str                # references tech_id or vehicle_id
    day: str                     # "Mon" .. "Fri"
    effect_type: str             # "unavailable" | "partial"
    effect_value: str            # reason / detail
```

### WeeklyData (container)

```python
@dataclass
class WeeklyData:
    jobs: list[Job]
    technicians: list[Technician]
    vehicles: list[Vehicle]
    exceptions: list[WeeklyException]
```

### ScheduleAssignment (Layer 1 output)

```python
@dataclass
class ScheduleAssignment:
    job_id: str
    tech_id: str
    vehicle_id: str
    day: str
    helper_tech_id: str | None   # set for J^H jobs
```

### RouteResult (Layer 2 output)

```python
@dataclass
class RouteResult:
    tech_id: str
    vehicle_id: str
    day: str
    visited_job_ids: list[str]   # ordered stop sequence
    dropped_job_ids: list[str]   # L1-assigned but infeasible in L2
    total_distance_m: float
    total_time_min: float
    objective_value: float
    solver_method: str           # "milp" | "sa" | "greedy" | "bfs"
    solver_status: str           # "optimal" | "feasible" | "timeout" | "infeasible"
```

### ReviewFlag

```python
@dataclass
class ReviewFlag:
    code: str                    # e.g. "DUP_ADDR", "ROUTE_DROP"
    severity: str                # "INFO" | "WARN" | "CRITICAL"
    message: str
    refs: dict                   # {"job_id": ..., "tech_id": ..., "route": ...}
```

### Exclusion

```python
@dataclass
class Exclusion:
    job_id: str
    reason_code: str             # e.g. "SKILL_MISMATCH", "CLUSTER_RADIUS"
    detail: str
```

---

## 4. Config Schema (`config.json`)

All numerical tuning parameters live in a version-controlled JSON file.
Airtable overrides take precedence when present (see Code/Config/Airtable split in `main.tex`).

```jsonc
{
  // --- Layer 1: Scheduling ---
  "lambda_uniformity": 50.0,       // workload-balance penalty weight
  "T_max_minutes": 480,            // daily time budget (service + travel)
  "P_max_stops": 14,               // global max stops per route
  "T_max_layer1_fraction": 0.80,   // conservative buffer for L1 (service-only)

  // --- Layer 2: Routing ---
  "R_cluster_radius_m": 30000,     // cluster radius from depot (metres)
  "r_interstop_limit_m": 15000,    // max gap between consecutive stops
  "R_increment_m": 5000,           // radius expansion step
  "R_max_iterations": 5,           // max cluster-expansion iterations
  "N_min_cluster": 5,              // minimum cluster size before expansion

  // --- Scoring ---
  "seasonal_weights": {
    "summer": { "w_g": 0.4, "w_f": 0.2, "w_a": 0.3, "w_r": 0.1 },
    "winter": { "w_g": 0.2, "w_f": 0.4, "w_a": 0.3, "w_r": 0.1 }
  },
  "summer_months": [3, 4, 5, 6, 7, 8, 9],

  // --- Solver ---
  "solver_timeout_sec": 120,
  "sa_T_start": 1000.0,
  "sa_alpha": 0.995,
  "sa_inner_iterations": 200,
  "random_seed": 42,

  // --- Validation ---
  "lat_bounds": [41.0, 48.0],
  "lon_bounds": [-74.0, -67.0],

  // --- Flags ---
  "weak_standby_threshold": 2,
  "veh_bottleneck_days": 4,
  "tech_overload_pct": 0.90
}
```

---

## 5. Rule-Evaluation Structure

Rules are evaluated in a strict stage sequence. Each stage narrows the feasible space before the next stage begins.

### Stage 1 — Input Validation (`validators.py`)

| Check | Action on failure |
|---|---|
| Required CSV columns present | Abort with consolidated error list |
| Coordinates within NE bounding box | Flag `GEOCODE_OOB`; exclude job |
| Referential integrity (exception scope_id → tech/vehicle) | Abort |
| No duplicate primary keys | Abort |
| Config schema valid (all keys present, in range) | Abort |
| At least one feasible (tech, vehicle, day) triple after exceptions | Abort |

### Stage 2 — Exclusion Filters (`pipeline.py` step 2)

```
for each job j:
    if j.status ∈ {"excluded", "cancelled", "assigned"}  → EXCLUDE (STATUS_EXCLUDED / ALREADY_ASSIGNED)
    if j flagged as urgent/manual                         → EXCLUDE (manual handling)
```

### Stage 3 — Apply Weekly Exceptions (`pipeline.py` step 3)

```
for each exception ex:
    if ex.scope_type == "technician":
        remove ex.day from technician[ex.scope_id].available_days
        (or reduce capacity if ex.effect_type == "partial")
    if ex.scope_type == "vehicle":
        remove ex.day from vehicle[ex.scope_id].available_days
```

Produces effective D_t and D_k sets used by all downstream stages.

### Stage 4 — Reserve Special Routes (`pipeline.py` step 4)

```
radiator_jobs  = [j for j in candidates if j.route_type == "radiator"]
nh_overnight   = [j for j in candidates if j.route_type == "nh_overnight"]
helper_jobs    = [j for j in candidates if j.helper_needed]

→ assign to reserved (tech, vehicle, day) slots
→ subtract consumed capacity
```

### Stage 5 — Eligibility Matrix (`eligibility.py`)

For each `(j, t, k, d)`:

```
e[j,t,k,d] = 1 iff ALL of:
    d ∈ D_t                                              # tech available
    d ∈ D_k                                              # vehicle available
    skill_t ⊇ req(j)                                     # skills match
    cap_k ⊇ ρ_j                                          # vehicle capabilities match
    haversine(y_t, x_t, lat_j, lon_j) ≤ R                # within cluster radius
    (t, j) ∉ prohibited_pairs                             # no prohibited pairing

# Helper eligibility (for j ∈ J^H):
e_H[j,t,d] = 1 iff ALL of:
    d ∈ D_t
    skill_t ⊇ req(j)
    haversine(y_t, x_t, lat_j, lon_j) ≤ R
```

### Stage 6 — Layer 1: Scheduling MILP (`scheduling/milp.py`)

Maximise weighted value minus uniformity penalty, subject to:
- `S1`: each job assigned at most once
- `S2`: eligibility
- `S3`: vehicle capacity per day
- `S4`: service-time budget (conservative: `T_max × T_max_layer1_fraction`)
- `S5–S6`: one vehicle per tech per day, one tech per vehicle per day
- `S7`: technician-day load (includes helper time)
- `S8`: uniformity deviation
- `S9–S11`: helper assignment, helper ≠ primary, helper eligibility

### Stage 7 — Layer 2: Cluster & Route (`routing/`)

For each `(tech_id, vehicle_id, day)` bundle from Layer 1:
1. Build geographic cluster (Algorithm 1 with radius expansion)
2. Compute distance sub-matrix (OSMnx, Haversine fallback)
3. Solve intra-cluster VRP (MILP → SA → Greedy → BFS cascade)
4. Verify post-route assertions

### Stage 8 — Post-processing (`postprocess/`)

- Rank standby jobs per route
- Compute area readiness (Good / Moderate / Lean)
- Generate review flags (10 codes, 3 severity levels)
- Generate exclusion report (11 reason codes)

---

## 6. Pseudocode — Weekly Run Flow

```python
def run_weekly_plan(config_path: str, data_dir: str) -> ReviewPackage:
    """Top-level pipeline orchestrator."""

    # ── 0. Load config ──────────────────────────────────────────────
    config = load_config(config_path)           # JSON/YAML + Airtable overrides

    # ── 1. Load & Normalise ─────────────────────────────────────────
    wd: WeeklyData = load_weekly_data(data_dir)

    # ── 2. Validate inputs ──────────────────────────────────────────
    errors = validate_inputs(wd, config)
    if errors:
        abort_with_report(errors)

    # ── 3. Exclude non-candidate jobs ───────────────────────────────
    candidates, exclusions = apply_exclusion_filters(wd.jobs)
    #   → exclusions: list[Exclusion] with reason codes

    # ── 4. Apply weekly exceptions ──────────────────────────────────
    apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)
    #   → mutates available_days on tech/vehicle objects

    # ── 5. Reserve special routes ───────────────────────────────────
    special_jobs, normal_jobs = split_special_routes(candidates)
    special_assignments = plan_special_routes(
        special_jobs, wd.technicians, wd.vehicles, config
    )
    consumed_capacity = compute_consumed_capacity(special_assignments)

    # ── 6. Layer 1: Schedule (MILP or greedy fallback) ──────────────
    eligibility = build_eligibility_matrix(
        normal_jobs, wd.technicians, wd.vehicles, config
    )
    helper_eligibility = build_helper_eligibility(
        [j for j in normal_jobs if j.helper_needed],
        wd.technicians, config
    )

    try:
        schedule: dict[(str, str, str), list[ScheduleAssignment]] = \
            solve_scheduling_milp(
                jobs=normal_jobs,
                technicians=wd.technicians,
                vehicles=wd.vehicles,
                eligibility=eligibility,
                helper_eligibility=helper_eligibility,
                consumed_capacity=consumed_capacity,
                config=config,
            )
    except SolverUnavailable:
        schedule = greedy_scheduling(
            normal_jobs, wd.technicians, wd.vehicles,
            eligibility, config
        )

    l1_exclusions = collect_unassigned_reasons(normal_jobs, schedule)
    exclusions.extend(l1_exclusions)

    # ── 7. Layer 1 assertion check ──────────────────────────────────
    l1_violations = verify_layer1(schedule, eligibility, config)
    #   → log violations; mark routes INFEASIBLE if any

    # ── 8. Layer 2: Cluster & Route (per bundle) ────────────────────
    all_routes: list[RouteResult] = []
    for (tech_id, veh_id, day), assignments in schedule.items():
        tech = lookup_tech(tech_id, wd.technicians)
        veh  = lookup_vehicle(veh_id, wd.vehicles)
        jobs_bundle = [a.job for a in assignments]

        # 8a. Build cluster
        cluster = build_cluster(
            tech, jobs_bundle, config.R_cluster_radius_m,
            config.N_min_cluster, config.R_increment_m,
            config.R_max_iterations
        )

        # 8b. Distance matrix
        dist_matrix = build_distance_matrix(tech, cluster)

        # 8c. Solve routing (cascade: MILP → SA → Greedy → BFS)
        route = solve_routing(
            cluster, dist_matrix, veh, config,
            methods=["milp", "sa", "greedy", "bfs"]
        )

        # 8d. Post-route assertions
        violations = verify_layer2(route, dist_matrix, veh, config)
        if violations:
            route.solver_status = "infeasible"
            log_violations(violations)

        all_routes.append(route)

        # 8e. Collect dropped jobs
        for jid in route.dropped_job_ids:
            exclusions.append(Exclusion(jid, "ROUTE_DROP", "..."))

    # ── 9. Merge special + normal routes ────────────────────────────
    all_routes = special_assignments.routes + all_routes

    # ── 10. Select standby jobs ─────────────────────────────────────
    unassigned_pool = get_unassigned_candidates(candidates, all_routes)
    standby = select_standby_per_route(
        all_routes, unassigned_pool, config
    )

    # ── 11. Area readiness ──────────────────────────────────────────
    readiness = compute_area_readiness(all_routes, standby, config)

    # ── 12. Review flags ────────────────────────────────────────────
    flags = generate_review_flags(
        all_routes, standby, wd, config
    )

    # ── 13. Render outputs ──────────────────────────────────────────
    write_flags_json(flags, output_dir)
    write_exclusions_json(exclusions, output_dir)
    write_route_summaries(all_routes, standby, readiness, output_dir)
    render_route_maps(all_routes, output_dir)
    write_airtable_snapshot(wd, output_dir)  # audit trail

    return ReviewPackage(
        routes=all_routes,
        standby=standby,
        readiness=readiness,
        flags=flags,
        exclusions=exclusions,
    )
```

---

## 7. Weekly Run Flow (Visual)

```
┌─────────────────────────────────────────────────┐
│  INPUTS                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ CSVs /   │ │ config   │ │ Airtable tables  │ │
│  │ ServiceM8│ │ .json    │ │ (weekly refresh)  │ │
│  └────┬─────┘ └────┬─────┘ └────────┬─────────┘ │
└───────┼─────────────┼────────────────┼───────────┘
        ▼             ▼                ▼
   ┌─────────────────────────────────────┐
   │  1. Load & Validate                 │
   │     • schema checks                 │
   │     • coordinate bounds             │
   │     • referential integrity         │
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  2. Exclude & Apply Exceptions      │
   │     • status filters                │
   │     • technician PTO / partial      │
   │     • vehicle maintenance           │
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  3. Reserve Special Routes          │
   │     • Radiator (V-2)               │
   │     • NH Overnight                  │
   │     • Helper / Two-Man              │
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  4. LAYER 1 — Scheduling MILP       │
   │     • build eligibility matrices    │
   │     • solve: max Σ w_j y - λ Σ dev │
   │     • fallback: greedy              │
   │     • output: (tech, veh, day) → [j]│
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  5. LAYER 2 — per (tech, veh, day)  │
   │     ┌──────────────────────┐        │
   │     │ 5a. Build cluster    │        │
   │     │ 5b. Distance matrix  │        │
   │     │ 5c. Solve VRP        │        │
   │     │     MILP → SA →      │        │
   │     │     Greedy → BFS     │        │
   │     │ 5d. Assert feasible  │        │
   │     └──────────────────────┘        │
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  6. Post-processing                 │
   │     • standby ranking               │
   │     • area readiness                │
   │     • review flags (10 codes)       │
   │     • exclusion report (11 codes)   │
   └───────────────┬─────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│  OUTPUTS                                        │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ route maps │ │ flags.json │ │ exclusions   │ │
│  │ per day    │ │            │ │ .json        │ │
│  └────────────┘ └────────────┘ └──────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ summaries  │ │ readiness  │ │ Airtable     │ │
│  │ .txt       │ │ lookup     │ │ snapshot     │ │
│  └────────────┘ └────────────┘ └──────────────┘ │
└─────────────────────────────────────────────────┘
```

---

## 8. Review Flags (quick reference)

| Code | Severity | Trigger |
|---|---|---|
| `DUP_ADDR` | INFO | ≥2 jobs share an address |
| `CROSS_AREA` | INFO | Route spans multiple areas |
| `WEAK_STANDBY` | WARN | <2 standby candidates for a route |
| `VEH_BOTTLENECK` | WARN | Vehicle at 100% capacity ≥4 days |
| `TECH_OVERLOAD` | WARN | Tech weekly load >90% available hours |
| `HELPER_TRAVEL` | WARN | Helper depot >R from primary depot |
| `ROUTE_DROP` | WARN | L1 job dropped during L2 routing |
| `SOLVER_TIMEOUT` | WARN | Solver hit time limit |
| `GEOCODE_OOB` | CRITICAL | Coordinates outside NE bounding box |
| `NO_FEASIBLE` | CRITICAL | L1 bundle has no feasible L2 route |

## 9. Exclusion Reason Codes (quick reference)

| Code | Meaning |
|---|---|
| `ALREADY_ASSIGNED` | Job assigned in a prior run |
| `STATUS_EXCLUDED` | Status is excluded / cancelled |
| `NO_ELIGIBLE_TRIPLE` | No (tech, vehicle, day) passes eligibility |
| `CAPACITY_FULL` | All eligible slots at vehicle capacity |
| `TIME_BUDGET` | Adding job exceeds T_max everywhere |
| `CLUSTER_RADIUS` | Job beyond R from all technician depots |
| `SKILL_MISMATCH` | No technician has required skills |
| `VEHICLE_MISMATCH` | No vehicle has required capabilities |
| `HELPER_UNAVAIL` | Helper needed but no second tech eligible |
| `PROHIBITED_PAIR` | All eligible techs are on the exclusion list |
| `ROUTE_DROP` | Scheduled by L1, dropped by L2 (travel infeasible) |

## 8. Testable Units

The design should make these units independently testable:

- input normalization
- exclusion filtering
- duplicate-address grouping
- capacity calculation
- special-route placement
- seasonal score weighting
- standby selection
- readiness computation
- review flag generation

## 9. Delivery Shape

The weekly engine run should output a review package with:

- structured route proposals
- assigned and standby job lists
- per-route and per-day maps
- review flags and reason codes
- area readiness summary
- plain-text readiness lookup block
```