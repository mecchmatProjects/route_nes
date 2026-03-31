# Technical Sketch — NES Rules-Driven Weekly Dispatch Engine

> Companion to `main.tex`. This document provides implementation-level detail:
> module outline, data schemas, pseudocode, rule-evaluation pipeline, config
> schema, and the weekly-run flow diagram.

---

## 1. Design Goal

Deliver a **deterministic, auditable** Python engine that:

1. Accepts four structured input payloads (Candidate Jobs, Weekly Context, Weekly Exceptions, Lookup/Rules Data).
2. Runs a rules-driven planning pipeline (Phase 1 = queue-based decision-ladder scheduling, Phase 2 = nearest-neighbour stop ordering).
3. Produces a draft weekly transcription calendar, review maps, communication records, and route flags — never auto-books into ServiceM8.
4. Is independently testable (no UI, no database, pure function pipeline).
5. Supports three callable workflows: Weekly Run, Replacement Job, and Replacement Route.

---

## 2. Module Outline

```text
nes_dispatch/
│
├── __init__.py
│
├── data/
│   ├── loaders.py            # CSV / Airtable readers → dataclasses
│   ├── models.py             # Job, Technician, Vehicle, WeeklyException,
│   │                         # WeeklyContext, AreaRule, WeeklyData,
│   │                         # PreRouteCommunication, RouteCommunication
│   └── validators.py         # Pre-run sanity checks (schema, coordinates, refs)
│
├── rules/                    # ── Phase 1 ──
│   ├── scoring.py            # Queue-based decision-ladder ranking (winter / summer)
│   ├── eligibility.py        # Named eligibility rules (VEH_WORK_ELIGIBLE, ROUTE_SHAPE_OK, etc.)
│   ├── slot_selection.py     # Best-fit ranking (closest depot, lightest day)
│   ├── helpers.py            # Helper-required flag per route/day (yes/no, not named)
│   └── workload.py           # Workload-review flags (no job movement)
│
├── routing/                  # ── Phase 2 ──
│   ├── distance.py           # Google Maps / routing-service travel-time computation
│   └── nearest_neighbour.py  # NN stop ordering + feasibility verification
│
├── postprocess/
│   ├── standby.py            # Standby job ranking (2 lowest-priority per route)
│   ├── readiness.py          # Area readiness computation (optional / pending Amy)
│   └── flags.py              # Review flags + Pre-Route / Route Communication records
│
├── mapping.py                # Route map rendering (labelled job pins, vehicle colour coding)
├── config.py                 # Loads JSON/YAML config; merges Airtable overrides
└── pipeline.py               # Top-level orchestrator (Weekly Run, Replacement Job,
                              #   Replacement Route callable workflows)
```

### Key conventions

| Convention | Detail |
|---|---|
| **Pure functions** | Every stage is `f(inputs, config) → outputs`. No global state. |
| **Named rules** | Every scheduling decision traces to a named rule (e.g. `VEH_WORK_ELIGIBLE`, `CAPACITY_OK`) and the data that triggered it. |
| **Deterministic** | Same inputs + config → identical outputs. No random seeds, no stochastic components. |
| **I/O at the edges** | Only `loaders.py` and `mapping.py` touch the filesystem or network. |

---

## 3. Schema Sketch

All domain objects are Python `@dataclass` instances defined in `data/models.py`.
Aligned with the NES Build Spec v7 four-payload input contract.

### Job (Candidate Jobs payload — spec Table 3)

```python
@dataclass
class Job:
    job_id: str                  # SM8-10452
    service_address: str
    city: str
    state: str
    area_number: str             # 2-digit normalised area ID
    area_name: str               # "Providence Core"
    job_category: str            # one of 17 spec categories
    queue: str                   # "Normal jobs" | "Priority" | ...
    created_date: str            # ISO date
    latitude: float              # WGS-84 (Airtable-owned, Python fallback)
    longitude: float
    required_job_hours: float    # 0.0 when not supplied
    total_job_amount: float      # for Accepted Quotes fallback
    radiator_count: int
    refinisher_location: str
    two_x_average_wait: bool     # Airtable-managed aging flag
    rebook_with_notes: int
    rebook_without_notes: int
    scheduling_preference: str   # pending Amy source
```

Key computed properties:
- `status` → derived from `queue` (eligible / excluded)
- `route_type` → derived from `job_category` (normal / radiator / nh_overnight / helper)
- `helper_needed` → `True` for Accepted Quotes + Two-Man categories
- `planned_hours` → fixed-hour, Required Job Hours, radiator-hours table, or AQ fallback (`total_job_amount / 350`, rounded up to next half-hour)
- `service_time_min` → `planned_hours * 60`
- `value` → `planned_hours * 150` (estimate)
- `age_days` → computed from `created_date`

### Technician

```python
@dataclass
class Technician:
    tech_id: str                 # T-01
    name: str                    # Mike
    home_lat: float              # depot
    home_lon: float
    available_days: list[str]    # D_t (before exceptions)
```

Note: spec says "do not assign specific helpers by name." Helper model is yes/no per route/day, configurable count (default 2).

### Vehicle (spec Table 8)

```python
@dataclass
class Vehicle:
    vehicle_id: str              # V-1
    vehicle_type: str            # "standard" | "radiator_only" | "overflow"
    capability_tags: list[str]
    available_days: list[str]    # D_k
    max_stops: int               # Q_k
```

Spec vehicle rules: 3 main vehicles (functionally equivalent), V-2 (radiator-only always), V-4 (light overflow — steam inspections, service calls, boiler maintenance only; no Accepted Quotes or Two-Man).

### WeeklyContext (spec Table 4)

```python
@dataclass
class WeeklyContext:
    week_of: str                 # Monday date
    season: str                  # "Winter" | "Summer"
    include_v4: bool
    helpers_available: int       # configurable, default 2
    holiday_list: str
```

### WeeklyException (spec Table 5)

```python
@dataclass
class WeeklyException:
    exception_id: str            # EX-2026-04-06-01
    week_of: str
    tech_or_slot: str            # "Mike", "Chris", etc.
    exception_type: str          # "Full technician-day block" (Initial build)
    affected_day: str            # "Monday" .. "Friday"
    notes: str
```

Note: Initial build assumes full technician-day blocks only. `scope_id` is a computed property returning `tech_or_slot`.

### AreaRule

```python
@dataclass
class AreaRule:
    area_number: str
    area_name: str
    adjacent_areas: str
    grouping_notes: str
    communication_label: str
```

### WeeklyData (container)

```python
@dataclass
class WeeklyData:
    jobs: list[Job]
    technicians: list[Technician]
    vehicles: list[Vehicle]
    exceptions: list[WeeklyException]
    context: list[WeeklyContext]
    area_rules: list[AreaRule]
```

### Communication Records (spec Tables 8–9)

```python
@dataclass
class PreRouteCommunication:
    comm_id: str
    comm_type: str               # "Skipped Job" | "Weak Route" | "Duplicate Review" | ...
    severity: str                # "Info" | "Warning" | "Action Needed"
    schedule_week: str
    message: str
    resolved: bool
    job_number: str
    route_day: str
    route_slot: str
    what_needs_fixing: str
    ai_suggested_action: str
    ryan_note: str
    created_by_run: str

@dataclass
class RouteCommunication:
    comm_id: str
    comm_type: str
    severity: str
    schedule_week: str
    message: str
    resolved: bool
    route_day: str               # required in post-sync interface
    route_slot: str              # required
    job_number: str
    affected_window: str         # e.g. "7-8 first slot"
    outside_normal_params: bool
    ryan_note: str
    created_by_run: str
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
Airtable overrides take precedence when present (see ownership boundaries in spec §10).

```jsonc
{
  // --- Phase 1: Scheduling ---
  "T_max_minutes": 480,            // daily time budget (service + travel)
  "T_max_phase1_fraction": 0.80,   // conservative buffer (service-only in Phase 1)

  // --- Route capacity ---
  "winter_booked": 4,              // standard route target: 4 booked + 2 standby
  "winter_booked_high_backlog": 5, // possible 5th booked when backlog high
  "summer_booked": 3,              // summer: 3 booked + 2 standby
  "standby_per_route": 2,

  // --- Geography ---
  "R_cluster_radius_m": 30000,     // cluster radius from depot (metres)
  "r_interstop_limit_m": 15000,    // max gap between consecutive stops

  // --- Scoring (decision-ladder tier order, per season) ---
  "winter_tier_order": ["Priority", "2x-average Normal", "Accepted Quotes = Scheduling Preferences", "Normal"],
  "summer_tier_order": ["Priority", "Accepted Quotes = Scheduling Preferences", "Normal"],
  "summer_months": [3, 4, 5, 6, 7, 8, 9],

  // --- Helpers ---
  "helpers_available_default": 2,

  // --- Workload review thresholds ---
  "tech_overload_pct": 0.90,
  "veh_bottleneck_days": 4,
  "weak_standby_threshold": 2,

  // --- Validation ---
  "lat_bounds": [41.0, 48.0],
  "lon_bounds": [-74.0, -67.0],

  // --- Booking windows ---
  "shop_departure_time": "07:00",
  "first_window_cutoff_minutes": 60,  // arrival < 8:00 → 7-8 window
  "window_sequence": ["7-8", "8-9", "8-11", "10-1", "11-2", "1-4", "2-5"]
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
    if j.queue ∈ {"Urgent", "On Hold"}                   → EXCLUDE (QUEUE_EXCLUDED)
    if j.queue not in known eligible/excluded queues      → EXCLUDE (UNKNOWN_QUEUE)
```

Note: spec §4 / §13 — "current status is not a required engine input." Queue placement
is the main control layer. Upstream pre-filtering should have already removed
cancelled/assigned jobs; the engine consumes queue meaning.

### Stage 3 — Apply Weekly Exceptions (`pipeline.py` step 3)

```
for each exception ex:
    resolve tech = lookup by ex.tech_or_slot (match tech_id or name)
    if tech found:
        remove ex.affected_day from tech.available_days
    # Initial build: full technician-day blocks only; no partial/vehicle exceptions yet
```

Produces effective D_t sets used by all downstream stages.

### Stage 4 — Reserve Special Routes (`pipeline.py` step 4)

```
radiator_jobs  = [j for j in candidates if j.job_category in RADIATOR_HOURS_CATEGORIES]
nh_jobs        = [j for j in candidates if j.route_type == "nh_overnight"]
two_man_jobs   = [j for j in candidates if j.helper_needed]

→ assign to reserved (tech, vehicle, day) slots
→ V-2 always radiator-only
→ subtract consumed capacity
```

### Stage 5 — Phase 1: Score & Schedule (`rules/`)

For each candidate job j (in decision-ladder order):

1. **Queue-based decision-ladder ranking (spec §6.1):**

   **Winter:** Priority → 2×-average Normal → Accepted Quotes / Requested Scheduling
   (equal tier, better route wins) → Normal jobs.

   **Summer:** Priority → Accepted Quotes / Requested Scheduling (equal tier,
   route quality decides) → Normal jobs. Aging is *not* an active scoring factor
   in summer.

   Within each tier, configurable weights determine final ordering.

2. **Check eligibility** — for each candidate (t, k, d) slot:

   | Rule | Condition |
   |---|---|
   | `VEH_WORK_ELIGIBLE` | vehicle can carry this job category (V-2 radiator-only, V-4 restricted) |
   | `ROUTE_SHAPE_OK` | job fits route geography (cluster, corridor, Providence-assisted) |
   | `POSITION_OK` | first-only / last-only constraint respected |
   | `TECH_AVAILABLE` | d ∈ D_t |
   | `VEH_AVAILABLE` | d ∈ D_k |
   | `CAPACITY_OK` | current stops for (k, d) < route target |
   | `TIME_OK` | current service for (t, d) + τ_j ≤ T_max × buffer |
   | `ONE_VEH_PER_TECH` | tech t not already using a different vehicle on day d |
   | `ONE_TECH_PER_VEH` | vehicle k not already assigned to a different tech on day d |

3. **Select best-fit slot** (closest depot → lightest day).

4. **Helper flag** (for helper-needed jobs): mark route/day as `helper_required = yes`.
   The engine does not assign helpers by name. If any job on a route requires a helper,
   the entire route/day is helper-required.

5. **Workload review:** flag `TECH_OVERLOAD` if any tech > 90% hours;
   flag `VEH_BOTTLENECK` if any vehicle at capacity 4+ days.

### Stage 6 — Phase 2: Order Stops (`routing/`)

For each (tech, vehicle, day) bundle from Phase 1:

1. **Nearest-neighbour sequencing:** start at depot, repeatedly visit the closest unvisited stop, return to depot.
2. **Feasibility verification:** walk the route and check:
   - Total travel + service time ≤ T_max → drop last-added job if violated (`ROUTE_DROP`)
   - Stop count ≤ Q_k
   - Inter-stop distance ≤ r → flag `CROSS_AREA` if violated (guidance only)
3. If any job is dropped, re-run NN on the reduced set.

### Stage 7 — Post-processing (`postprocess/`)

- Rank standby jobs per route (2 lowest-priority among otherwise acceptable candidates)
- Generate Pre-Route Communications (one record per issue: skipped jobs, weak routes, duplicates)
- Compute area readiness (optional / pending Amy)
- Generate transcription-calendar output (5-column weekday × 4 route-row grid; job numbers only)
- Generate review flags and exclusion report

---

## 6. Pseudocode — Weekly Run Flow

```python
def run_weekly_plan(config_path: str, data_dir: str) -> ReviewPackage:
    """Top-level pipeline orchestrator — Weekly Run callable workflow."""

    # ── 0. Load config ──────────────────────────────────────────────
    config = load_config(config_path)           # JSON/YAML + Airtable overrides

    # ── 1. Load & Normalise (4-payload contract) ────────────────────
    wd: WeeklyData = load_weekly_data(data_dir)
    #   wd.jobs            ← Candidate Jobs
    #   wd.context         ← Weekly Context
    #   wd.exceptions      ← Weekly Exceptions
    #   wd.area_rules      ← Lookup / Rules Data
    #   wd.technicians     ← from Lookup / Rules
    #   wd.vehicles        ← from Lookup / Rules

    # ── 2. Validate inputs ──────────────────────────────────────────
    errors = validate_inputs(wd, config)
    if errors:
        abort_with_report(errors)

    # ── 3. Exclude by queue (spec §4) ──────────────────────────────
    candidates, exclusions = apply_exclusion_filters(wd.jobs)
    #   Urgent, On Hold → excluded; eligible queues pass through

    # ── 4. Apply weekly exceptions ──────────────────────────────────
    apply_exceptions(wd.technicians, wd.vehicles, wd.exceptions)
    #   Full technician-day blocks only for Initial build

    # ── 5. Reserve special routes ───────────────────────────────────
    special_jobs, normal_jobs = split_special_routes(candidates)
    special_assignments = plan_special_routes(
        special_jobs, wd.technicians, wd.vehicles, config
    )
    consumed_capacity = compute_consumed_capacity(special_assignments)

    # ── 6. Phase 1: Decision-Ladder Schedule (spec §6.1) ───────────
    season = wd.context[0].season if wd.context else "Winter"
    ranked_jobs = decision_ladder_rank(normal_jobs, season, config)

    schedule = {}          # (tech_id, vehicle_id, day) → [ScheduleAssignment]
    phase1_exclusions = []
    pre_route_comms = []   # PreRouteCommunication records

    for job in ranked_jobs:
        best_slot = find_best_eligible_slot(
            job, wd.technicians, wd.vehicles, config, schedule,
            consumed_capacity
        )
        if best_slot:
            assign(job, best_slot, schedule)
            if job.helper_needed:
                mark_route_helper_required(best_slot, schedule)
        else:
            phase1_exclusions.append(
                Exclusion(job.job_id, first_failing_rule(job), "...")
            )
            pre_route_comms.append(
                PreRouteCommunication(
                    comm_type="Skipped Job", severity="Warning",
                    message=f"Job {job.job_id} skipped: {first_failing_rule(job)}",
                    job_number=job.job_id,
                    what_needs_fixing="Review eligibility and rerun."
                )
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

    # ── 10. Standby, communications, transcription calendar ─────────
    unassigned = get_unassigned(candidates, all_routes)
    standby = select_standby_per_route(all_routes, unassigned, config)
    readiness = compute_area_readiness(all_routes, standby, config)  # optional
    flags = generate_review_flags(all_routes, standby, wd, config)
    flags.extend(workload_flags)

    # Transcription calendar: 5 weekday columns × 4 route rows
    calendar = build_transcription_calendar(all_routes, wd)

    write_outputs(all_routes, standby, readiness, flags, exclusions,
                  pre_route_comms, calendar)

    return ReviewPackage(
        routes=all_routes, standby=standby,
        readiness=readiness, flags=flags, exclusions=exclusions,
        pre_route_comms=pre_route_comms, calendar=calendar,
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
   │     • queue-based exclusion          │
   │       (Urgent / On Hold)            │
   │     • full technician-day blocks    │
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
   │     • queue-based decision ladder   │
   │     • 9 named eligibility rules     │
   │     • best-fit slot selection       │
   │     • helper-required flag pass     │
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
│  │ transcr.   │ │ Pre-Route  │ │ Route        │ │
│  │ calendar   │ │ Comms      │ │ Comms        │ │
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

> `SOLVER_TIMEOUT` is reserved for a future phase if a TSP/VRP solver is introduced. Not used in Initial build.

## 9. Exclusion Reason Codes (quick reference)

| Code | Meaning |
|---|---|
| `QUEUE_EXCLUDED` | Job queue is Urgent or On Hold — excluded from weekly engine |
| `UNKNOWN_QUEUE` | Job queue not in known eligible/excluded set |
| `NO_ELIGIBLE_TRIPLE` | No (tech, vehicle, day) passes all 9 eligibility rules |
| `CAPACITY_FULL` | All eligible slots at vehicle capacity |
| `TIME_BUDGET` | Adding job exceeds T_max everywhere |
| `VEHICLE_MISMATCH` | No vehicle has required capabilities for this job category |
| `ROUTE_SHAPE` | Job does not fit acceptable route geography |
| `POSITION_CONFLICT` | First-only / last-only constraint cannot be satisfied |
| `ROUTE_DROP` | Scheduled by Phase 1, dropped by Phase 2 (travel infeasible) |
| `MISSING_GEOCODE` | Job could not be geocoded; skipped with communication record |
| `INVALID_CATEGORY` | Job category not in the 17 spec categories |

Note: `ALREADY_ASSIGNED`, `STATUS_EXCLUDED`, `CLUSTER_RADIUS`, `SKILL_MISMATCH`, `HELPER_UNAVAIL`, and `PROHIBITED_PAIR` from the pre-spec design are superseded. See `rule_classification.md` §5.2 for details.

## 10. Testable Units

The design should make these units independently testable:

- input normalisation and validation
- exclusion filtering (queue-based)
- duplicate-address grouping
- queue-based decision-ladder ranking
- 9 named eligibility rules (individual and combined)
- best-fit slot selection
- helper-required flag logic
- nearest-neighbour sequencing
- feasibility verification and job dropping
- capacity tracking
- special-route placement
- standby selection
- area readiness computation
- review flag generation

## 11. Delivery Shape

The Weekly Run callable workflow should output a review package with:

- transcription-calendar output (5 weekday × 4 route-row grid; job numbers only)
- assigned, standby, and anchor-hold job lists per route
- per-route and per-day maps (labelled job pins, vehicle colour coding, route notes)
- Pre-Route Communications (one record per issue, before ServiceM8 transcription)
- Route Communications (one record per issue, in post-sync route interface)
- review flags and exclusion reason codes
- area readiness summary (optional / pending Amy)
- helper-required = yes/no per route/day
- first-only / last-only position flags
- booking-window feasibility notes

The engine also exposes two day-recovery workflows:

- **Replacement Job** — from post-sync single-route view; returns up to 2 unranked
  replacement candidates (or 1 + outside-normal-parameters flag)
- **Replacement Route** — from same route view; rebuilds that one day for same
  technician/route, including new standby selection
```