# NES Scheduling Engine Requirements

## 1. Purpose

This document converts the sprint brief in `task.pdf` into a structured set of product and engineering requirements for the Python scheduling engine.

The target is a maintainable, rules-driven weekly planning engine for New England SteamWorks. The engine proposes a draft weekly schedule for human review. It is not a booking app, not a route navigation product, and not a direct calendar writer.

## 2. Scope

### In Scope

- Weekly draft schedule generation for Ryan's review and manual ServiceM8 transcription.
- Three callable workflows: Weekly Run, Replacement Job, Replacement Route.
- Four-payload input contract: Candidate Jobs, Weekly Context, Weekly Exceptions, Lookup/Rules Data.
- Queue-based decision-ladder ranking (winter / summer variants).
- Geographic grouping and route/day proposal generation (clusters, corridors, Providence-assisted).
- Vehicle work-type constraints (V-2 radiator-only, V-4 overflow restrictions).
- Weekly exception handling (full technician-day blocks in Initial build).
- Special route handling before normal route filling (radiator, NH overnight, Two-Man).
- Helper-required flagging per route/day (yes/no, not named assignment).
- Standby job selection (2 lowest-priority per route).
- Anchor-hold identification.
- Booking-window feasibility flagging and first-only / last-only constraints.
- Pre-Route and Route Communications (one record per issue).
- Transcription-calendar output (5 weekday × 4 route-row grid; job numbers only).
- Map generation for each proposed route/day.
- Area readiness output (optional / pending Amy).

### Out of Scope

- Direct writes into the ServiceM8 calendar.
- Customer booking or invitation management.
- Assigning specific helpers by name.
- Full downstream Airtable / ServiceM8 invite lifecycle.
- Appointment-time optimization.
- Revision-code logic (deferred until testing).
- Generic freeform communication button.
- Airtable base implementation or UI design.
- Machine learning features.
- Overbuilt optimization architecture.

## 3. System Boundaries

### Systems

- ServiceM8: system of record for jobs and operational data.
- Airtable: scheduling rules, structured inputs, review layers, outputs, radiator-hours table, and communication surfaces.
- Python engine: planning, evaluation, ranking, proposal generation, and output packaging.

### Ownership Boundaries (spec §10)

| Freelancer owns | Amy / Airtable owns | Shared interface |
|---|---|---|
| Weekly engine logic; route selection; geography logic; aging/fairness application; helper-required flags; route maps; draft schedule outputs; replacement/day-recovery recommendation logic. | Airtable display/storage; dashboard/workflow UX; queue/status automations; ServiceM8 note-writing and message generation; radiator-hours table. | Input/export schemas; review handoff; replacement/rebuild triggers/buttons; any Area Readiness storage/display split. |

### Boundary Rule

The Python engine must be independently understandable and testable. It should consume structured inputs (four-payload contract) and produce structured outputs without embedding Airtable or automation-specific logic inside the planning core.

## 4. Planning Model

### Planning Horizon

- The engine plans one full week at a time.
- Planning must be route-first, not day-first.

### Required Planning Stages

1. Load and validate the four input payloads.
2. Exclude by queue (Urgent, On Hold).
3. Apply weekly exceptions (full technician-day blocks).
4. Reserve capacity for special route types first (radiator V-2, NH, Two-Man).
5. Rank and schedule normal jobs via queue-based decision ladder.
6. Order stops via nearest-neighbour + feasibility verification.
7. Select standby jobs (2 per route) and identify anchor-hold jobs.
8. Generate Pre-Route Communications, Route Communications, transcription calendar, maps, flags, and exclusion report.
9. Compute area readiness (optional / pending Amy).

## 5. Functional Requirements

### 5.1 Candidate Pool Processing

- The engine shall accept a prefiltered candidate pool of eligible Work Order jobs.
- The engine shall assume jobs already scheduled, canceled, or manually handled as Urgent are excluded upstream before the engine runs (spec §3).
- The engine shall exclude Urgent and On Hold queues. All other queue values pass to planning.
- Queue placement is the main control layer; current status is not a required engine input (spec §13).

### 5.2 Weekly Exceptions

- The engine shall incorporate weekly exceptions before route filling.
- Initial build exceptions are full technician-day blocks only (spec §5, Table 5).
- Weekly Exceptions are the authoritative source of within-week availability reduction.
- Pre-existing calendar load is represented through Weekly Exceptions, not live ServiceM8 calendar access (spec §13).

### 5.3 Geography and Route Grouping

- The engine shall be route-first and geography-aware.
- Area boundaries shall act as guidance, not hard walls.
- Neighboring areas may be mixed when geography meaningfully improves route quality.
- The engine shall preserve enough geographic coherence for owner review and downstream customer communication.

### 5.4 Seasonal Fairness

- The engine shall apply seasonal weighting to fairness and aging pressure.
- Season (winter or summer) is owner-selected per-week in the Weekly Context payload, not derived from calendar months.
- In summer, geography shall dominate more strongly.
- In winter, fairness and aging shall receive more weight while still respecting geographic sanity.

### 5.5 Human Review Model

- The engine shall output a draft transcription calendar for Ryan's review and manual ServiceM8 transcription.
- The engine shall not auto-write into the ServiceM8 calendar.
- The engine shall not directly book customers or send invitations.
- Ryan-to-AI actions use standard buttons: Run AI Analysis, Approve, Reject / Re-run, Replacement Job, Replacement Route.
- Acceptance standard: the goal of the project is that AI does the scheduling work, not Ryan. Most live weeks should be approved by Ryan with no changes (spec §14.4).

### 5.6 Special Route Types

- The engine shall process special route types before normal route filling.
- Initial build must explicitly support:
  - Radiator Runs
  - NH Overnight Runs
  - Two-Man or helper-needed routes

### 5.7 Vehicle Rules (spec Table 8)

- Three main vehicles are functionally equivalent — no restrictions between them.
- V-2 is radiator-only always. Do not use as a normal standard route.
- V-4 is a light overflow route (winter only, toggled via Weekly Context). Allowed: steam system inspections, service calls, boiler maintenance. Cannot do Accepted Quotes or helper-required / Two-Man routes.
- Current practical daily route capacity is 4 route slots: 3 named technicians + V-4 when active.

### 5.8 Standby Jobs and Day-Recovery

- The engine shall output assigned jobs separately from standby jobs.
- Standby jobs are the 2 lowest-priority jobs among otherwise acceptable route candidates (spec §7).
- If enough valid standby jobs do not exist, the route normally should not run unless work is thin.
- The engine must also support Replacement Job (up to 2 unranked candidates) and Replacement Route (rebuild one day) as callable workflows (spec §7, §14.3).

### 5.9 Duplicate Address Handling

- Duplicate policing should primarily happen upstream in Airtable before Python scheduling begins (spec §8.2).
- If a suspected duplicate still slips through, Python may surface it through Pre-Route Communications.
- Multiple radiator replacement slave jobs at 15 Monticello, Providence must never be treated as duplicates.
- Where duplicate review is still needed, the flag should be minimal: Job # and what needs fixing.

### 5.10 Area Readiness

- Area Readiness scope is optional / pending Amy (spec §10.2, §12).
- Current best assumption: if Airtable can calculate it, Airtable should own it.
- The engine does not need to own Area Readiness calculation in Initial build unless later directed.

### 5.11 Maps

- The engine shall generate a plotted map for each proposed route/day.
- Maps must include: job pins labelled with Job #, job category, and planned hours; vehicle colour coding; route notes.
- Five pre-route maps should be delivered on the Schedule Week record in the first interface.
- **Implemented:** `nes_dispatch/mapping.py` renders per-route PNG maps.

## 6. Data and Configuration Requirements

### Required Inputs (four-payload contract, spec §2)

1. **Candidate Jobs** — job ID, created date/age, address, city, state, area number/name, job category, queue, required job hours, total job amount, radiator count, refinisher location, 2×-average flag, rebook counts, scheduling preference.
2. **Weekly Context** — week of, season, include V-4, holiday list, linked exceptions.
3. **Weekly Exceptions** — exception ID, week of, tech/slot, exception type (full-day block), affected day, notes.
4. **Lookup / Rules Data** — technician/vehicle/area lookup, area naming, adjacency/grouping rules, restriction flags.

### Derived by Python

- Drive times / travel-time calculations at runtime via a real routing service (Google Maps).
- Geocodes when Airtable cannot supply them (Python fallback; skip job if geocoding fails).
- Planned hours via category-based rules (fixed, Required Job Hours, radiator-hours table, AQ fallback).
- Special-route definitions.

### Configuration Principle

- Owner-tunable policy should live in configuration or Airtable-managed rule tables.
- Stable deterministic logic should live in Python code.
- Pure review annotations and workflow status flags should stay outside the planning core when possible.

## 7. Output Requirements

### Primary Outputs (spec Table 12)

- Transcription-calendar output (5 weekday × 4 route-row grid; job numbers only).
- Route grouping output (assigned, standby, anchor-hold jobs shown distinctly).
- Route flags (helper required yes/no; first-only / last-only; odd-route explanation).
- Day/route maps (labelled job pins, vehicle colour coding, route notes).
- Pre-Route Communications (one record per issue, before ServiceM8 transcription).
- Route Communications (one record per issue, post-sync route interface).
- Area report / readiness (optional / pending Amy).

### Output Characteristics

- Outputs shall be traceable to the rules that produced them.
- Outputs shall be readable by a non-technical owner.
- Outputs shall separate hard-failure reasons from soft preference tradeoffs.

## 8. Quality Requirements

- The engine shall be maintainable and easy to modify.
- The decision flow shall be explainable to a non-technical owner.
- The planning logic shall avoid black-box behavior.
- The system shall support deterministic re-runs for the same inputs and configuration.
- The design shall support testing even with limited historical engine-style data.

## 9. Initial Build Requirements

Initial build should:

- Produce a reliable weekly draft transcription calendar plus review artifacts.
- Implement three callable workflows: Weekly Run, Replacement Job, Replacement Route.
- Use queue-based decision-ladder ranking (not composite scoring formula).
- Use hard constraints for eligibility and safety.
- Produce Pre-Route and Route Communications (one record per issue).
- Support booking-window feasibility flagging and first-only / last-only constraints.
- Produce review-ready artifacts without writing directly to the ServiceM8 calendar.
- Use real upcoming live scheduling weeks for testing (spec §14.4).

Initial build should not:

- Assign specific helpers by name.
- Compute final revision-code logic (deferred until testing).
- Attempt appointment-time optimization.
- Depend on speculative AI or predictive models.
- Introduce solver-heavy architecture before simpler rule-driven planning is proven insufficient.
- Own the full downstream Airtable / ServiceM8 invite lifecycle.
- Build a generic freeform communication button.

### Acceptance criteria (spec §14.4)

- Testing uses the real upcoming live scheduling week.
- Ryan may start as early as Monday; freelancer may revise up to Thursday.
- If output is not usable by Thursday, Ryan reverts to manual for that week.
- Most live weeks should be approved by Ryan with no changes.
- The goal of the project is that AI does the scheduling work, not Ryan.
- If two live weeks fail, the project pauses automatically for review.

## 10. Risks and Ambiguities

- Scheduling Preferences detail source — queue is settled, exact source of preference text pending Amy.
- Radiator module — radiator-hour formulas live in Airtable, editable there; Ryan still needs to set first real values.
- 2×-average-wait trigger source — Airtable will supply the flag.
- Area Readiness final scope — optional / pending Amy.
- Exception interaction channel — required system capability, implementation owner TBD.
- Revision-loop schema — structured reason codes for why a week's plan may need republishing; deferred until testing.
- Hosting/deployment details — technical handoff needed; should remain a compact appendix.

### Superseded assumptions (spec §13)

- Current status is not a required engine input.
- "Backup jobs" → use assigned, standby, and anchor-hold.
- Scheduling Preferences ≠ rebook-age rule.
- V-4 is not a full equivalent route slot.
- Pre-existing calendar load → via Weekly Exceptions, not live ServiceM8 access.

## 11. Acceptance Criteria For Discovery Phase

The discovery work is complete when the repository contains:

- A structured problem statement aligned with the NES Build Spec v7.
- A recommended Python engine design with three callable workflows.
- A clear ownership-boundary split (Python / Airtable / Shared).
- A rule classification into hard constraints, eligibility filters, decision-ladder ranking, and review flags.
- A technical sketch of modules, schemas, and weekly run flow.
- An Initial build recommendation with explicit assumptions, deferred items, and live-week testing protocol.