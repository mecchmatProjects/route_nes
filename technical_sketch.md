# Technical Sketch — NES Rules-Driven Weekly Dispatch Engine

> Companion to `main.tex`. This document provides implementation-level detail:
> module outline, data schemas, pseudocode, rule-evaluation pipeline, config
> schema, and the weekly-run flow diagram.

---

## 1. Design Goal

Deliver a **deterministic, auditable** Python engine that:

1. Accepts structured weekly data (jobs, technicians, vehicles, exceptions).
2. Runs a rules-driven planning pipeline (Phase 1 = score-and-assign scheduling, Phase 2 = nearest-neighbour stop ordering).
3. Produces reviewable route proposals, review flags, and exclusion reports — never auto-books.
4. Is independently testable (no UI, no database, pure function pipeline).
5. Requires no external solver, optimisation library, or random component.

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
├── rules/                    # ── Phase 1 ──
│   ├── scoring.py            # Composite priority-score formula
│   ├── eligibility.py        # 10 named eligibility rules → pass/fail per slot
│   ├── slot_selection.py     # Best-fit ranking (closest depot, lightest day, cheapest vehicle)
│   ├── helpers.py            # Helper-assignment secondary pass
│   └── workload.py           # Workload-review flags (no job movement)
│
├── routing/                  # ── Phase 2 ──
│   ├── distance.py           # Haversine distance computation
│   └── nearest_neighbour.py  # NN stop ordering + feasibility verification
│
├── postprocess/
│   ├── standby.py            # Standby job ranking
│   ├── readiness.py          # Area readiness computation (Good / Moderate / Lean)
│   └── flags.py              # Review flags (9 active codes, 3 severity levels)
│
├── mapping.py                # Route map rendering (OSMnx road graphs + Matplotlib)
├── config.py                 # Loads JSON/YAML config; merges Airtable overrides
└── pipeline.py               # Top-level orchestrator (the 9-step weekly pipeline)
```

### Key conventions

| Convention | Detail |
|---|---|
| **Pure functions** | Every stage is `f(inputs, config) → outputs`. No global state. |
| **Named rules** | Every scheduling decision traces to a named rule (e.g. `SKILL_MATCH`, `CAPACITY_OK`) and the data that triggered it. |
| **Deterministic** | Same inputs + config → identical outputs. No random seeds, no stochastic components. |
| **I/O at the edges** | Only `loaders.py` and `mapping.py` touch the filesystem or network. |

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

### ScheduleAssignment (Phase 1 output)

```python
@dataclass
class ScheduleAssignment:
    job_id: str
    tech_id: str
    vehicle_id: str
    day: str
    helper_tech_id: str | None   # set for J^H jobs
```

### RouteResult (Phase 2 output)

```python
@dataclass
class RouteResult:
    tech_id: str
    vehicle_id: str
    day: str
    visited_job_ids: list[str]   # ordered stop sequence
    dropped_job_ids: list[str]   # Phase-1-assigned but infeasible in Phase 2
    total_distance_m: float
    total_time_min: float
    method: str                  # "nearest_neighbour"
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
  // --- Phase 1: Scheduling ---
  "T_max_minutes": 480,            // daily time budget (service + travel)
  "T_max_phase1_fraction": 0.80,   // conservative buffer (service-only in Phase 1)
  "P_max_stops": 14,               // global max stops per route

  // --- Phase 2: Routing ---
  "R_cluster_radius_m": 30000,     // cluster radius from depot (metres)
  "r_interstop_limit_m": 15000,    // max gap between consecutive stops

  // --- Scoring ---
  "seasonal_weights": {
    "summer": { "w_g": 0.4, "w_f": 0.2, "w_a": 0.3, "w_r": 0.1 },
    "winter": { "w_g": 0.2, "w_f": 0.4, "w_a": 0.3, "w_r": 0.1 }
  },
  "summer_months": [3, 4, 5, 6, 7, 8, 9],

  // --- Workload review thresholds ---
  "tech_overload_pct": 0.90,       // flag if tech weekly load > 90% of capacity
  "veh_bottleneck_days": 4,        // flag if vehicle at 100% capacity >= N days
  "weak_standby_threshold": 2,     // flag if fewer than N standby candidates per route

  // --- Validation ---
  "lat_bounds": [41.0, 48.0],
  "lon_bounds": [-74.0, -67.0]
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

### Stage 5 — Phase 1: Score & Schedule (`rules/`)

For each candidate job j (in descending score order):

1. **Compute composite score:**
   ```
   score_j = w_g·geo_j + w_f·fair_j + w_a·age_j + w_r·readiness_j
   ```

2. **Check eligibility** — for each candidate (t, k, d) slot, all 10 rules must pass:

   | Rule | Condition |
   |---|---|
   | `TECH_AVAILABLE` | d ∈ D_t |
   | `VEH_AVAILABLE` | d ∈ D_k |
   | `SKILL_MATCH` | skill_t ⊇ req(j) |
   | `VEH_CAPABILITY` | cap_k ⊇ ρ_j |
   | `WITHIN_RADIUS` | haversine(depot_t, job_j) ≤ R |
   | `NOT_PROHIBITED` | (t, j) ∉ prohibited pairs |
   | `CAPACITY_OK` | current stops for (k, d) < Q_k |
   | `TIME_OK` | current service time for (t, d) + τ_j ≤ T_max × buffer |
   | `ONE_VEH_PER_TECH` | tech t not already using a different vehicle on day d |
   | `ONE_TECH_PER_VEH` | vehicle k not already assigned to a different tech on day d |

3. **Select best-fit slot** (closest depot → lightest day → cheapest vehicle).

4. **Helper pass** (for j ∈ J^H): find a second tech ≠ primary; same eligibility minus vehicle rules.

5. **Workload review:** flag `TECH_OVERLOAD` if any tech > 90% hours; flag `VEH_BOTTLENECK` if any vehicle at capacity 4+ days.

### Stage 6 — Phase 2: Order Stops (`routing/`)

For each (tech, vehicle, day) bundle from Phase 1:

1. **Nearest-neighbour sequencing:** start at depot, repeatedly visit the closest unvisited stop, return to depot.
2. **Feasibility verification:** walk the route and check:
   - Total travel + service time ≤ T_max → drop last-added job if violated (`ROUTE_DROP`)
   - Stop count ≤ Q_k
   - Inter-stop distance ≤ r → flag `CROSS_AREA` if violated (guidance only)
3. If any job is dropped, re-run NN on the reduced set.

### Stage 7 — Post-processing (`postprocess/`)

- Rank standby jobs per route
- Compute area readiness (Good / Moderate / Lean)
- Generate review flags (9 active codes, 3 severity levels)
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

    # ── 4. Apply weekly exceptions ──────────────────────────────────
    apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)

    # ── 5. Reserve special routes ───────────────────────────────────
    special_jobs, normal_jobs = split_special_routes(candidates)
    special_assignments = plan_special_routes(
        special_jobs, wd.technicians, wd.vehicles, config
    )
    consumed_capacity = compute_consumed_capacity(special_assignments)

    # ── 6. Phase 1: Score & Schedule (rules-based) ──────────────────
    scored_jobs = score_jobs(normal_jobs, config)
    scored_jobs.sort(key=lambda j: (-j.score, -j.age_days, -j.value))

    schedule = {}          # (tech_id, vehicle_id, day) → [ScheduleAssignment]
    phase1_exclusions = []

    for job in scored_jobs:
        best_slot = find_best_eligible_slot(
            job, wd.technicians, wd.vehicles, config, schedule,
            consumed_capacity
        )
        if best_slot:
            assign(job, best_slot, schedule)
            if job.helper_needed:
                helper = find_helper(job, best_slot.day, wd.technicians,
                                     config, schedule)
                if not helper:
                    unassign(job, schedule)
                    phase1_exclusions.append(
                        Exclusion(job.job_id, "HELPER_UNAVAIL", "...")
                    )
        else:
            phase1_exclusions.append(
                Exclusion(job.job_id, first_failing_rule(job), "...")
            )

    exclusions.extend(phase1_exclusions)

    # ── 7. Phase 1 workload review ──────────────────────────────────
    workload_flags = check_workload(schedule, wd.technicians, config)

    # ── 8. Phase 2: Order Stops (nearest-neighbour) ─────────────────
    all_routes: list[RouteResult] = []
    for (tech_id, veh_id, day), assignments in schedule.items():
        tech = lookup_tech(tech_id, wd.technicians)
        veh  = lookup_vehicle(veh_id, wd.vehicles)
        jobs = [a.job for a in assignments]

        # 8a. Nearest-neighbour sequencing
        route_order = nearest_neighbour(tech.depot, jobs)

        # 8b. Feasibility check — drop jobs if T_max exceeded
        route, dropped = verify_feasibility(route_order, veh, config)
        for jid in dropped:
            exclusions.append(Exclusion(jid, "ROUTE_DROP", "..."))

        all_routes.append(route)

    # ── 9. Merge special + normal routes ────────────────────────────
    all_routes = special_assignments.routes + all_routes

    # ── 10. Standby, readiness, flags, outputs ──────────────────────
    unassigned = get_unassigned(candidates, all_routes)
    standby = select_standby_per_route(all_routes, unassigned, config)
    readiness = compute_area_readiness(all_routes, standby, config)
    flags = generate_review_flags(all_routes, standby, wd, config)
    flags.extend(workload_flags)

    write_outputs(all_routes, standby, readiness, flags, exclusions)

    return ReviewPackage(
        routes=all_routes, standby=standby,
        readiness=readiness, flags=flags, exclusions=exclusions,
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
   │  4. PHASE 1 — Score & Schedule      │
   │     • composite priority scoring    │
   │     • 10 named eligibility rules    │
   │     • best-fit slot selection       │
   │     • helper assignment pass        │
   │     • workload review flags         │
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  5. PHASE 2 — Order Stops           │
   │     per (tech, vehicle, day):       │
   │     ┌──────────────────────┐        │
   │     │ 5a. NN sequencing    │        │
   │     │ 5b. Feasibility check│        │
   │     │ 5c. Drop if T_max   │        │
   │     │     exceeded         │        │
   │     └──────────────────────┘        │
   └───────────────┬─────────────────────┘
                   ▼
   ┌─────────────────────────────────────┐
   │  6. Post-processing                 │
   │     • standby ranking               │
   │     • area readiness                │
   │     • review flags (9 codes)        │
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
| `ROUTE_DROP` | WARN | Phase-1-scheduled job dropped during Phase 2 routing |
| `GEOCODE_OOB` | CRITICAL | Coordinates outside NE bounding box |
| `NO_FEASIBLE` | CRITICAL | Phase 1 bundle has no feasible Phase 2 route |

> `SOLVER_TIMEOUT` is reserved for future Version 2 if a TSP/VRP solver is introduced. Not used in V1.

## 9. Exclusion Reason Codes (quick reference)

| Code | Meaning |
|---|---|
| `ALREADY_ASSIGNED` | Job assigned in a prior run |
| `STATUS_EXCLUDED` | Status is `excluded` or `cancelled` |
| `NO_ELIGIBLE_TRIPLE` | No (tech, vehicle, day) passes all 10 eligibility rules |
| `CAPACITY_FULL` | All eligible slots at vehicle capacity |
| `TIME_BUDGET` | Adding job exceeds T_max everywhere |
| `CLUSTER_RADIUS` | Job beyond R from all technician depots |
| `SKILL_MISMATCH` | No technician has required skills |
| `VEHICLE_MISMATCH` | No vehicle has required capabilities |
| `HELPER_UNAVAIL` | Helper needed but no second tech eligible |
| `PROHIBITED_PAIR` | All eligible techs on exclusion list |
| `ROUTE_DROP` | Scheduled by Phase 1, dropped by Phase 2 (travel infeasible) |

## 10. Testable Units

The design should make these units independently testable:

- input normalisation and validation
- exclusion filtering
- duplicate-address grouping
- composite priority scoring
- 10 named eligibility rules (individual and combined)
- best-fit slot selection
- helper assignment logic
- nearest-neighbour sequencing
- feasibility verification and job dropping
- capacity tracking
- special-route placement
- standby selection
- area readiness computation
- review flag generation

## 11. Delivery Shape

The weekly engine run should output a review package with:

- structured route proposals
- assigned and standby job lists
- per-route and per-day maps
- review flags and reason codes
- area readiness summary
- plain-text readiness lookup block
```