# Rule Classification

This document classifies the scheduling logic described in `task.pdf` into implementation categories so the Python engine can stay maintainable.

## 1. Hard Constraints

These rules decide whether a job, technician, vehicle, or route combination is allowed.

| Rule | Description | Expected Output When Violated |
| --- | --- | --- |
| Candidate pool eligibility | Job must be in the valid weekly planning pool | Excluded with reason code |
| Already handled exclusions | Scheduled, canceled, urgent/manual, already-in-workflow jobs must not enter normal planning | Excluded with reason code |
| Technician availability | Technician must be available after weekly exceptions are applied | Infeasible assignment or reduced capacity |
| Vehicle availability | Vehicle must be available for the week and route type | Infeasible assignment or reduced capacity |
| Special route prerequisites | Radiator, NH Overnight, and helper-needed jobs must satisfy route-type requirements | Unassigned with route-type reason |
| Required vehicle assignment | V-2 required for Radiator Runs | Infeasible route if unavailable |
| Helper requirement | Two-Man or helper-needed jobs require sufficient staffing | Unassigned with staffing reason |
| Prohibited pairings | Invalid tech/vehicle/job combinations must not be proposed | Excluded assignment option |

## 2. Eligibility Filters

These rules remove or narrow candidates before route scoring.

| Rule | Description | Typical Stage |
| --- | --- | --- |
| Weekly candidate import filter | Accept only jobs intended for this planning run | Input preprocessing |
| Exclusion flags | Remove canceled, urgent/manual, and already-handled jobs | Input preprocessing |
| Weekly exception application | Subtract unavailable technicians, vehicles, and consumed capacity | Capacity build |
| Duplicate-address grouping | Group related jobs at the same address for route-shape evaluation | Preplanning normalization |
| Special-route extraction | Pull special-route jobs out of the normal pool first | Preplanning normalization |

## 3. Weighted or Preference Logic

These rules rank feasible proposals rather than allowing or disallowing them.

| Logic | Description | Notes |
| --- | --- | --- |
| Geographic compactness | Prefer cleaner route shape and shorter cross-area jumps | Base scoring driver |
| Seasonal fairness weighting | Increase fairness and aging pressure in October through February | Seasonal parameter set |
| Aging pressure | Raise jobs that have waited longer | Soft pressure, not absolute |
| Area blending preference | Allow neighboring areas to mix when route quality improves | Guidance, not hard wall |
| Standby usefulness | Prefer backups that are plausible substitutes for assigned work | Route-specific or area-specific |
| Area readiness support | Prefer proposals that produce credible communication coverage | Should not override route sanity |

## 4. Owner-Controlled Policy Inputs

These items should be editable without changing Python logic.

| Policy Input | Suggested Home |
| --- | --- |
| Seasonal scoring weights | Config or Airtable |
| Area readiness thresholds | Config or Airtable |
| Area metadata and labels | Airtable |
| Special route definitions | Airtable |
| Temporary planning overrides | Airtable |
| Standby depth targets | Config or Airtable |
| Distance and adjacency thresholds | Config |

## 5. Review Flags and Exception Outputs

These outputs should be visible to the owner and downstream workflow.

| Flag | Why It Matters |
| --- | --- |
| Duplicate-address detected | Prevents misleading route density and hidden multi-job sites |
| Unassigned special-route job | Highlights capacity or policy shortfall |
| Vehicle bottleneck | Explains missing route capacity |
| Technician bottleneck | Explains shortage-driven deferral |
| Cross-area route blend | Signals geography tradeoff that may need review |
| Weak readiness area | Supports communication review |
| Low-quality standby pool | Warns that substitution options are thin |

## 6. Design Guidance

Use this classification as an implementation rule:

1. Hard constraints should produce explicit pass or fail decisions.
2. Eligibility filters should happen before route scoring.
3. Weighted logic should stay parameterized.
4. Review flags should be emitted even when the plan is otherwise valid.
5. Owner-controlled policy should not be hard-coded into the planning core unless stability is required.