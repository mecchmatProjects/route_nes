# NES Scheduling Engine Requirements

## 1. Purpose

This document converts the sprint brief in `task.pdf` into a structured set of product and engineering requirements for the Python scheduling engine.

The target is a maintainable, rules-driven weekly planning engine for New England SteamWorks. The engine proposes a draft weekly schedule for human review. It is not a booking app, not a route navigation product, and not a direct calendar writer.

## 2. Scope

### In Scope

- Weekly dispatch-planning logic in Python.
- Candidate-job evaluation for the current planning week.
- Geographic grouping and route/day proposal generation.
- Technician and vehicle compatibility checks.
- Weekly exception handling.
- Special route handling before normal route filling.
- Standby job selection.
- Area readiness output.
- Map generation for each proposed route/day.
- Structured outputs for downstream review and automation.

### Out of Scope

- Full production implementation.
- UI design.
- Airtable base implementation.
- Make or Zapier workflow design.
- Direct writes into the ServiceM8 calendar.
- Exact stop sequencing.
- Appointment-time assignment.
- Machine learning features.
- Overbuilt optimization architecture unless clearly required by Version 1.

## 3. System Boundaries

### Systems

- ServiceM8: system of record for jobs and operational data.
- Airtable: scheduling rules, structured inputs, review layers, and outputs.
- Make or Zapier: orchestration and automation.
- Python engine: planning, evaluation, scoring, proposal generation, and output packaging.

### Boundary Rule

The Python engine must be independently understandable and testable. It should consume structured inputs and produce structured outputs without embedding Airtable or automation-specific logic deep inside the planning core.

## 4. Planning Model

### Planning Horizon

- The engine plans one full week at a time.
- Planning must be route-first, not day-first.

### Required Planning Stages

1. Load the weekly candidate pool.
2. Subtract exclusions and jobs already handled elsewhere.
3. Apply weekly exceptions and real capacity reductions.
4. Reserve capacity for special route types first.
5. Build normal route/day proposals.
6. Select backup or standby jobs.
7. Compute area readiness outputs.
8. Produce maps and structured review artifacts.

## 5. Functional Requirements

### 5.1 Candidate Pool Processing

- The engine shall accept a prefiltered candidate pool for the target week.
- The engine shall assume jobs already scheduled, canceled, urgent/manual, already in workflow, or otherwise excluded are removed before normal planning.
- The engine shall still support explicit exclusion flags in case upstream filtering is incomplete.

### 5.2 Weekly Exceptions

- The engine shall incorporate weekly exceptions before route filling.
- Weekly exceptions shall include at least technician unavailability, vehicle unavailability, pre-scheduled long jobs, and boiler installs already consuming capacity.
- Weekly capacity shall be computed from weekly exceptions, not only from technician master data.

### 5.3 Geography and Route Grouping

- The engine shall be route-first and geography-aware.
- Area boundaries shall act as guidance, not hard walls.
- Neighboring areas may be mixed when geography meaningfully improves route quality.
- The engine shall preserve enough geographic coherence for owner review and downstream customer communication.

### 5.4 Seasonal Fairness

- The engine shall apply seasonal weighting to fairness and aging pressure.
- In March through September, geography shall dominate more strongly.
- In October through February, fairness and aging shall receive more weight while still respecting geographic sanity.

### 5.5 Human Review Model

- The engine shall output a draft schedule for human review.
- The engine shall not auto-book jobs into the calendar.
- The engine shall not promise dates early.
- The engine shall not assign exact stop order or appointment times in Version 1.

### 5.6 Special Route Types

- The engine shall process special route types before normal route filling.
- Version 1 must explicitly support:
  - Radiator Runs
  - NH Overnight Runs
  - Two-Man or helper-needed routes

### 5.7 Vehicle Rules

- The engine shall enforce vehicle constraints when building capacity and route proposals.
- V-2 shall be used for Radiator Runs.
- V-4 shall act as a weekly capacity switch.
- V-5, V-6, and V-7 shall be treated as standard service vehicles.

### 5.8 Standby Jobs

- The engine shall output assigned jobs separately from standby jobs.
- Standby jobs shall be plausible replacement jobs that can be used when assigned jobs drop out.

### 5.9 Duplicate Address Handling

- The engine shall detect duplicate-address or same-address job groups.
- The engine shall flag these groups for review.
- The engine shall not silently delete them.
- Same-address jobs shall not inflate stop density when evaluating route shape.

### 5.10 Area Readiness

- The engine shall output Area Readiness as a communication layer.
- Allowed readiness values shall be `Good`, `Moderate`, and `Lean`.
- The engine shall also produce a plain-text lookup block for downstream use.

### 5.11 Maps

- The engine shall generate a plotted map for each proposed route/day.
- Maps are a required review artifact.

## 6. Data and Configuration Requirements

### Required Inputs

- Candidate jobs for the planning week.
- Job geography and address data.
- Area assignments or area metadata.
- Technician roster and technician capabilities.
- Vehicle roster and vehicle capabilities.
- Weekly exceptions.
- Policy settings for geography, fairness, and route behavior.
- Special-route definitions.

### Configuration Principle

- Owner-tunable policy should live in configuration or Airtable-managed rule tables.
- Stable deterministic logic should live in Python code.
- Pure review annotations and workflow status flags should stay outside the planning core when possible.

## 7. Output Requirements

### Primary Outputs

- Proposed weekly route/day assignments.
- Standby job list.
- Route maps.
- Area readiness values.
- Review flags and exception notes.

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

## 9. Version 1 Requirements

Version 1 should:

- Solve the weekly route proposal problem with transparent rules.
- Prioritize clarity and maintainability over aggressive optimization.
- Use hard constraints for eligibility and safety.
- Use weighted scoring for route quality, fairness, and backup selection.
- Produce review-ready artifacts without writing directly to the operational calendar.

Version 1 should not:

- Attempt exact route sequencing.
- Attempt appointment-time optimization.
- Depend on speculative AI or predictive models.
- Introduce solver-heavy architecture before simpler rule-driven planning is proven insufficient.

## 10. Risks and Ambiguities

- Exact input schemas for ServiceM8 and Airtable are not defined in the brief.
- Some route-type rules may contain additional exceptions not yet documented.
- Area readiness calculation thresholds are not specified numerically.
- Seasonal weighting is described conceptually, not mathematically.
- Capacity modeling for long jobs and installs may require policy decisions before implementation.

## 11. Acceptance Criteria For Discovery Phase

The discovery work is complete when the repository contains:

- A structured problem statement.
- A recommended Python engine design.
- A clear split between code, configuration, and Airtable-managed policy.
- A rule classification into hard constraints, filters, weights, and review flags.
- A technical sketch of modules, schemas, and weekly run flow.
- A Version 1 recommendation with explicit assumptions and risks.