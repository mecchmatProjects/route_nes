# Discovery Memo

## 1. Problem Understanding

New England SteamWorks needs a weekly dispatch-planning engine — specifically a **draft-generation and review-support tool** for Ryan's manual ServiceM8 transcription, not a booking workflow or calendar app. The engine's job is to turn a four-payload input contract (Candidate Jobs, Weekly Context, Weekly Exceptions, Lookup/Rules Data) into a **transcription calendar** (5 weekday columns × 4 route rows) plus review artifacts (communications, maps, exclusion report) that Ryan can trust and transcribe.

The core operational characteristic is queue-based, route-first planning. The engine should first classify jobs by queue priority (Priority → AQ/RS → Normal, with seasonal variants), resolve exceptions and exclusions (Urgent / On Hold → excluded), then build routes using vehicle / tech / capacity / geography constraints.

This is also not a black-box optimization problem. The spec is explicit that the system must remain maintainable, understandable by a non-technical owner, and easy to adjust over time. That favors a layered decision-ladder engine with transparent ranking over an opaque, fully solver-driven planner.

## 2. Recommended Engine Structure

The Python engine should be organized as a pipeline with clear separation between data normalization, rule evaluation, planning, and output rendering.

Recommended layers:

1. Input adapters
   Load four-payload contract from Airtable CSV exports. Gracefully skip jobs with missing/bad geocodes.
2. Domain normalisation
   Convert raw records into typed dataclasses (Job with 17+ fields and computed properties, Technician, Vehicle, WeeklyContext, WeeklyException, AreaRule).
3. Queue-based exclusion
   Remove Urgent / On Hold jobs. Apply Weekly Exceptions (full tech-day blocks). Annotate excluded jobs with reason codes.
4. Decision-ladder ranking
   Winter: Priority → 2×-average Normal → AQ/RS → Normal. Summer: Priority → AQ/RS → Normal. Aging active in winter only.
5. Eligibility filtering
   VEH_WORK_ELIGIBLE, ROUTE_SHAPE_OK, POSITION_OK, TECH_AVAILABLE, VEH_AVAILABLE, CAPACITY_OK, TIME_OK, ONE_VEH_PER_TECH, ONE_TECH_PER_VEH.
6. Route shaping
   Build geography-aware route/day proposals. Route targets: winter 4 booked + 2 standby, summer 3 booked + 2 standby. V-4 overflow toggle.
7. Helper flagging
   Per route/day yes/no flag. If any job on a route needs a helper, the route is helper-required. Configurable count (default 2). No named assignment.
8. Standby + anchor-hold identification
   Rank 2 standby jobs per route. Tag anchor-hold jobs. Replacement Job / Replacement Route callable workflows.
9. Review artifact generator
   Transcription calendar (5×4 grid), Pre-Route Communications, Route Communications, per-route maps, exclusion report.

This structure matches the spec's operational flow (§6–§9) and gives a clean place for owner-managed policy settings without leaking those settings across the whole codebase.

## 3. Code vs Config vs Airtable Split

### Code

Code should contain deterministic logic that must remain consistent and testable:

- schema validation and normalization
- hard eligibility checks
- vehicle compatibility checks
- capacity calculations
- route-building workflow
- scoring execution
- map generation (implemented in `mapping.py` using OSMnx road-network graphs)
- output generation

### Config

Configuration should contain values that are stable but environment-specific or tunable by technical staff:

- T_max (daily time budget)
- route targets (winter 4+2, summer 3+2)
- booking-window parameters
- distance and adjacency thresholds
- standby selection limits
- workload-review thresholds

### Airtable-Managed Policy (Amy-Airtable ownership, spec §10)

Airtable should manage owner-controlled policy that changes as the business evolves:

- Candidate Jobs export (17 fields per spec Table 3)
- Weekly Context (season, V-4 toggle, helpers_available, holiday_list)
- Weekly Exceptions (tech_or_slot, day, reason)
- Lookup/Rules Data (radiator-hours table, area grouping rules)
- Review statuses and communication records (Pre-Route / Route)

### Shared ownership (spec §10)

- Field dictionary (addendum Tables 1–4) is the binding interface contract.
- Changes to field names or types require coordinated Airtable + code updates.

This split keeps the engine disciplined. If too much policy goes into code, maintenance slows down. If too much algorithmic logic goes into Airtable formulas, testing and explainability degrade.

## 4. Hard Constraints vs Decision-Ladder Ranking

The spec supports a mixed model.

Hard constraints (eligibility checks) govern whether something is allowed at all. The decision ladder governs preference among allowed options by queue tier, not by numeric score.

Hard constraints (eligibility checks) include:

- VEH_WORK_ELIGIBLE — vehicle type can handle the job category
- ROUTE_SHAPE_OK — job fits the geographic shape of the route
- POSITION_OK — no scheduling conflicts (booking-window, duplicate day)
- TECH_AVAILABLE — technician not blocked by Weekly Exception
- VEH_AVAILABLE — vehicle not blocked for the day
- CAPACITY_OK — route not at capacity (winter 4, summer 3 booked slots)
- TIME_OK — total service + travel fits within T_max
- ONE_VEH_PER_TECH / ONE_TECH_PER_VEH — pairing uniqueness per day

Queue-based decision-ladder ranking (replaces weighted scoring):

- Winter: Priority → 2×-average Normal → AQ/RS (equal tier) → Normal
- Summer: Priority → AQ/RS (equal tier) → Normal
- Aging active in winter only
- Geographic compactness evaluated within each tier

This is the right tradeoff for the Initial build because the business is rules-heavy and queue-driven, not numerically optimised.

## 5. Geography, Queue Priority, and Area Readiness Interaction

Geography should be the base organizing principle. The weekly plan should produce routes that are spatially coherent and reviewable.

Queue priority determines which jobs rise within feasible geographic clusters. The decision ladder (not a numeric scoring formula) governs tier placement. Within each tier, geographic fit and aging break ties.

Seasonal variation selects the decision-ladder variant:

- Summer (roughly March–September): Priority → AQ/RS → Normal. Geography dominates.
- Winter (roughly October–February): Priority → 2×-average Normal → AQ/RS → Normal. Aging pressure elevates long-waiting jobs.

The `season` value is supplied per-week in the Weekly Context payload; Ryan selects it.

Area Readiness is optional / pending Amy (spec §8). When active, it adds adjacency/grouping constraints to route shaping. It should not drive route construction directly as a hard wall.

## 6. Initial Build Recommendation

The Initial build should be a transparent, queue-driven weekly planner with a decision-ladder and review artifacts.

Recommended Initial build behavior:

- exclude Urgent / On Hold jobs by queue
- apply Weekly Exceptions (full tech-day blocks)
- rank by seasonal decision ladder, not composite scores
- check eligibility via named rules (VEH_WORK_ELIGIBLE, ROUTE_SHAPE_OK, etc.)
- shape routes with geography + vehicle constraints
- flag helper-required routes (yes/no, no named assignment)
- generate 2 standby jobs per route, identify anchor-holds
- emit transcription calendar, communications, per-route maps, exclusion report
- support 3 callable workflows: Weekly Run, Replacement Job, Replacement Route
- avoid direct ServiceM8 writes — Ryan transcribes manually

Recommended Initial build implementation style:

- pure Python planning core
- configuration-driven thresholds (T_max, route targets, booking windows)
- traceable reason codes on exclusions and route assignments
- four-payload input contract as the binding interface
- live-week testing with real data; Thursday deadline; two-failure pause rule

## 7. Major Risks and Ambiguities

The Build Spec v7 and Clarification Addendum resolved most of the original discovery risks. Remaining items:

| Risk | Status |
|---|---|
| Exact input schemas | ✅ RESOLVED — Four-payload field dictionaries in spec Tables 3–6 + addendum. |
| Special route type rules | ✅ RESOLVED — 17-category table with planned-hours sources, V-2/V-4 restrictions. |
| Area readiness thresholds | ⚠️ OPEN — Optional / pending Amy. |
| Route capacity representation | ✅ RESOLVED — Winter 4+2, Summer 3+2 per route; booking-window feasibility check. |
| Geographic precision | ✅ RESOLVED — Google Maps lat/lon + Distance Matrix; bad geocodes gracefully skipped. |
| 2×-average-wait trigger | ⚠️ OPEN — Airtable will supply the flag; field/formula unspecified. |
| Radiator-hours table values | ⚠️ OPEN — Ryan needs to set initial values. |
| Named helper assignment | ✅ RESOLVED — Deferred; yes/no flag only. |
| Revision-code logic | ✅ DEFERRED — Until testing reveals real failure modes. |

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

The strongest Initial build is a queue-driven decision-ladder engine that produces an explainable transcription calendar, structured communications, and review artifacts. The main pitfall to avoid is jumping too early into heavy optimization or automation before the policy model is stable and observable through live-week testing.