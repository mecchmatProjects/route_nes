# Discovery Memo

## 1. Problem Understanding

New England SteamWorks needs a weekly dispatch-planning engine, not a booking workflow. The engine's job is to turn a prefiltered weekly candidate pool into reviewable route/day proposals that balance geography, capacity, technician and vehicle fit, special-route requirements, fairness, and area readiness.

The core operational characteristic is route-first planning. The engine should not start from a calendar and try to fill days in isolation. It should first understand the weekly demand shape, the available weekly capacity, and the jobs that must be treated specially before normal route construction begins.

This is also not a black-box optimization problem. The brief is explicit that the system must remain maintainable, understandable by a non-technical owner, and easy to adjust over time. That favors a layered rules engine with transparent scoring over an opaque, fully solver-driven planner.

## 2. Recommended Engine Structure

The Python engine should be organized as a pipeline with clear separation between data normalization, rule evaluation, planning, and output rendering.

Recommended layers:

1. Input adapters
   Read structured data from ServiceM8 and Airtable exports or API responses.
2. Domain normalization
   Convert raw records into stable internal models for jobs, technicians, vehicles, exceptions, and policy settings.
3. Eligibility and hard-constraint evaluation
   Remove impossible assignments and annotate jobs with exclusion reasons.
4. Capacity builder
   Compute true weekly route capacity from technician availability, vehicle availability, long jobs, installs, and route-type reservations.
5. Special-route planner
   Place Radiator Runs, NH Overnight Runs, and helper-required jobs before normal filling.
6. Normal route proposal planner
   Build geography-aware weekly route/day proposals using weighted scoring.
7. Standby selector
   Produce plausible substitute jobs by route and week.
8. Review artifact generator
   Emit maps, area readiness, route summaries, flags, and traceable outputs.

This structure matches the brief's operational flow and gives a clean place for owner-managed policy settings without leaking those settings across the whole codebase.

## 3. Code vs Config vs Airtable Split

### Code

Code should contain deterministic logic that must remain consistent and testable:

- schema validation and normalization
- hard eligibility checks
- vehicle compatibility checks
- capacity calculations
- route-building workflow
- scoring execution
- map and output generation

### Config

Configuration should contain values that are stable but environment-specific or tunable by technical staff:

- scoring weights by season
- readiness thresholds
- route size targets
- distance and adjacency thresholds
- standby selection limits

### Airtable-Managed Policy

Airtable should manage owner-controlled policy that changes as the business evolves:

- route-type definitions
- helper-required flags
- special handling rules
- area labels and communication metadata
- temporary planning overrides
- review statuses and manual approval fields

This split keeps the engine disciplined. If too much policy goes into code, maintenance slows down. If too much algorithmic logic goes into Airtable formulas, testing and explainability degrade.

## 4. Hard Constraints vs Weighted Logic

The brief supports a mixed model.

Hard constraints should govern whether something is allowed at all. Weighted logic should govern preference among allowed options.

Hard constraints include:

- job is eligible for this week's planning pool
- technician is available this week
- required vehicle is available
- route type prerequisites are satisfied
- helper-required jobs have adequate staffing
- prohibited pairings are not allowed

Weighted logic includes:

- geographic compactness
- seasonal fairness pressure
- aging pressure
- area readiness improvement
- standby usefulness
- route practicality when areas slightly cross over

This is the right tradeoff for Version 1 because the business appears rules-heavy but still judgment-driven.

## 5. Geography, Fairness, and Area Readiness Interaction

Geography should be the base organizing principle. The weekly plan should produce routes that are spatially coherent and reviewable.

Fairness should adjust which jobs rise within feasible geographic clusters. It should not routinely destroy route shape.

Seasonal variation should change the scoring balance:

- March through September: stronger emphasis on clean geography.
- October through February: stronger emphasis on fairness and aging, constrained by geographic sanity.

Area Readiness should not drive route construction directly as a hard wall. It should be derived from the shape and density of actual proposed activity so that customer communication remains credible.

## 6. Version 1 Recommendation

Version 1 should be a transparent, rules-driven weekly planner with weighted scoring and review artifacts.

Recommended Version 1 behavior:

- use explicit hard filters before scoring
- pre-build weekly capacity from real exceptions
- place special routes first
- cluster and score normal routes second
- generate standby jobs separately
- emit route maps, flags, and readiness outputs
- avoid direct calendar writes
- avoid exact stop-order optimization

Recommended Version 1 implementation style:

- pure Python planning core
- configuration-driven weights and thresholds
- traceable reason codes on exclusions and route assignments
- stable output schemas for downstream Airtable and automation consumption

## 7. Major Risks and Ambiguities

The main discovery risks are not algorithmic complexity. They are policy clarity and data shape clarity.

Highest-risk ambiguities:

1. exact input schemas from ServiceM8 and Airtable
2. detailed business rules for special route types
3. formal definitions for area readiness thresholds
4. how route capacity should be represented when long jobs partially consume a technician-week
5. what level of geographic precision is available and trustworthy

If these are left vague, the engine can still be built, but the first implementation will carry more assumptions than is ideal.

## 8. Validation and Testing Approach

Because there may be limited historical engine-style data, testing should combine fixture-based validation and scenario-driven review.

Recommended test strategy:

1. schema tests
   validate required fields and normalization behavior
2. rule tests
   verify each hard constraint and each review flag independently
3. scoring tests
   verify score ordering under controlled scenarios
4. weekly scenario tests
   run small synthetic planning weeks covering edge cases such as vehicle loss, helper routes, duplicate addresses, and seasonal changes
5. replay tests
   compare engine recommendations against a small set of manually reviewed historical weeks
6. review artifact checks
   verify each route/day produces maps, readable summaries, and reason codes

## 9. Recommendation Summary

The strongest Version 1 is a practical rules-and-scoring engine that produces explainable weekly route proposals and review artifacts. The main pitfall to avoid is jumping too early into heavy optimization or automation before the policy model is stable and observable.