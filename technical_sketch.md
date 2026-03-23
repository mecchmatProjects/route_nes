# Technical Sketch

## 1. Design Goal

Provide a practical Version 1 Python engine for weekly scheduling that is rules-driven, explainable, and easy to evolve.

## 2. Module Outline

```text
engine/
  adapters/
    servicem8_loader.py
    airtable_loader.py
  domain/
    models.py
    enums.py
  policy/
    config.py
    seasonal_weights.py
  rules/
    eligibility.py
    capacity.py
    special_routes.py
    review_flags.py
  planning/
    candidate_pool.py
    clustering.py
    scorer.py
    planner.py
    standby.py
    readiness.py
  outputs/
    serializers.py
    maps.py
    summaries.py
  app.py
```

## 3. Schema Sketch

### Job

```python
Job(
    job_id: str,
    address_id: str,
    area_id: str | None,
    latitude: float | None,
    longitude: float | None,
    required_route_type: str | None,
    requires_helper: bool,
    age_days: int,
    priority_flags: list[str],
    status_flags: list[str],
)
```

### Technician

```python
Technician(
    tech_id: str,
    name: str,
    skills: list[str],
    available_days: list[str],
)
```

### Vehicle

```python
Vehicle(
    vehicle_id: str,
    vehicle_type: str,
    available_days: list[str],
    capability_tags: list[str],
)
```

### Weekly Exception

```python
WeeklyException(
    exception_id: str,
    scope_type: str,
    scope_id: str,
    start_date: str,
    end_date: str,
    effect_type: str,
    effect_value: str,
)
```

### Route Proposal

```python
RouteProposal(
    route_id: str,
    week_key: str,
    day_key: str,
    route_type: str,
    technician_ids: list[str],
    vehicle_id: str | None,
    area_ids: list[str],
    assigned_job_ids: list[str],
    standby_job_ids: list[str],
    score: float,
    reason_codes: list[str],
    review_flags: list[str],
)
```

## 4. Rule-Evaluation Structure

Use a staged evaluation model.

### Stage 1: Normalize Inputs

- validate required fields
- standardize identifiers
- attach area and address grouping metadata

### Stage 2: Build Candidate Pool

- remove excluded jobs
- separate special-route candidates
- group same-address jobs for route-shape purposes

### Stage 3: Build Weekly Capacity

- apply technician exceptions
- apply vehicle exceptions
- subtract known long-job capacity consumption
- reserve capacity for special routes

### Stage 4: Evaluate Hard Constraints

- technician fit
- vehicle fit
- helper-required staffing
- route-type prerequisites

### Stage 5: Score Feasible Proposals

Example score model:

$$
score = w_g \cdot geography + w_f \cdot fairness + w_a \cdot aging + w_r \cdot readiness + w_s \cdot standby\_utility
$$

Where the weight vector changes by season.

### Stage 6: Emit Review Outputs

- route summaries
- review flags
- readiness lookup block
- plotted maps

## 5. Weekly Run Flow

```text
load inputs
  -> normalize records
  -> build candidate pool
  -> apply exclusions
  -> build weekly capacity
  -> reserve special routes
  -> plan special routes
  -> plan normal routes
  -> select standby jobs
  -> compute area readiness
  -> render maps and summaries
  -> export review package
```

## 6. Pseudocode

```python
def run_weekly_planning(week_context):
    normalized = normalize_inputs(week_context)

    candidates = build_candidate_pool(normalized.jobs)
    candidates = apply_exclusion_filters(candidates, normalized)

    grouped_candidates = group_duplicate_addresses(candidates)

    capacity = build_weekly_capacity(
        technicians=normalized.technicians,
        vehicles=normalized.vehicles,
        exceptions=normalized.exceptions,
        existing_commitments=normalized.commitments,
    )

    special_jobs, normal_jobs = split_special_route_jobs(grouped_candidates)

    special_plan = plan_special_routes(
        jobs=special_jobs,
        capacity=capacity,
        policy=normalized.policy,
    )

    remaining_capacity = reduce_capacity(capacity, special_plan)

    normal_plan = plan_normal_routes(
        jobs=normal_jobs,
        capacity=remaining_capacity,
        policy=normalized.policy,
        season=normalized.week.season,
    )

    standby = select_standby_jobs(
        unassigned_jobs=normal_plan.unassigned_jobs,
        assigned_routes=normal_plan.routes,
        policy=normalized.policy,
    )

    readiness = compute_area_readiness(
        routes=normal_plan.routes,
        standby=standby,
        policy=normalized.policy,
    )

    review_package = build_review_package(
        special_plan=special_plan,
        normal_plan=normal_plan,
        standby=standby,
        readiness=readiness,
    )

    render_route_maps(review_package)
    return review_package
```

## 7. Version 1 Algorithm Choice

Version 1 should use explicit rule filtering plus weighted heuristic planning.

Recommended approach:

1. rule-based prefiltering for feasibility
2. lightweight clustering by geography or adjacency
3. weighted scoring inside feasible clusters
4. greedy or iterative route assembly with reason codes

Not recommended for Version 1:

- exact global optimization across the full week
- stop-order routing optimization
- solver-heavy capacity assignment before rules are stable

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