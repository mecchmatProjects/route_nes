# Rule Classification — NES Rules-Driven Weekly Dispatch Engine

> Companion to `main.tex` (system specification) and `technical_sketch.md` (implementation detail).
> This document classifies every scheduling and routing rule into five categories
> so the Python engine (`nes_dispatch/`) stays maintainable, testable, and auditable.

---

## 1. Hard Constraints

Hard constraints produce a binary **pass / fail** decision.  
A violated hard constraint means the assignment or route is **infeasible** — the engine must never output it.

### 1.1 Phase 1 — Scheduling (named eligibility rules)

| ID | Rule | Eligibility rule name | Violated → |
|---|---|---|---|
| H-01 | **Each job assigned at most once** across all (tech, vehicle, day) triples | (structural) | Duplicate assignment prevented |
| H-02 | **Technician available on day** after weekly exceptions | `TECH_AVAILABLE` | Blocked; contributes to `NO_ELIGIBLE_TRIPLE` |
| H-03 | **Vehicle available on day** after weekly exceptions | `VEH_AVAILABLE` | Blocked; contributes to `NO_ELIGIBLE_TRIPLE` |
| H-04 | **Vehicle work-type eligible** — V-2 radiator-only, V-4 restricted to inspections/service calls/boiler maintenance | `VEH_WORK_ELIGIBLE` | Blocked; reason `VEHICLE_MISMATCH` |
| H-05 | **Route shape acceptable** — cluster, corridor, or Providence-assisted | `ROUTE_SHAPE_OK` | Blocked; reason `ROUTE_SHAPE` |
| H-06 | **Position constraint respected** — first-only / last-only | `POSITION_OK` | Blocked; reason `POSITION_CONFLICT` |
| H-07 | **Route capacity per day** — stops ≤ route target (winter 4+2, summer 3+2) | `CAPACITY_OK` | Excess job excluded; reason `CAPACITY_FULL` |
| H-08 | **Service-time budget** — total per day ≤ T_max × buffer | `TIME_OK` | Excess job excluded; reason `TIME_BUDGET` |
| H-09 | **One vehicle per technician per day** | `ONE_VEH_PER_TECH` | Vehicle re-assignment prevented |
| H-10 | **One technician per vehicle per day** | `ONE_TECH_PER_VEH` | Tech re-assignment prevented |
| H-11 | **V-4 excluded from Accepted Quotes and Two-Man routes** | `VEH_WORK_ELIGIBLE` | V-4 slot rejected |

Note: the spec removes `SKILL_MATCH`, `WITHIN_RADIUS`, `NOT_PROHIBITED`, and `HELPER_UNAVAIL` from the Initial build eligibility set. Skills are not modelled per-technician (3 main techs are functionally equivalent). Helper is a yes/no flag per route, not a named assignment. Prohibited pairings are deferred.

### 1.2 Phase 2 — Routing (nearest-neighbour feasibility checks)

| ID | Rule | Implementation | Violated → |
|---|---|---|---|
| H-13 | **Depart from and return to depot** | NN algorithm structure | Route structurally invalid |
| H-14 | **No stop visited more than once** | NN algorithm structure | Duplicate visit prevented |
| H-15 | **Total travel + service time ≤ T_max** | Feasibility verification | Last-added job dropped; reason `ROUTE_DROP` |
| H-16 | **Stops ≤ Q_k** (vehicle capacity) | Feasibility verification | Excess stop dropped |
| H-17 | **Every stop within radius R of depot** | Enforced by Phase 1 geography (`ROUTE_SHAPE_OK`) | Should not occur; flag `GEOCODE_OOB` if violated |

### 1.3 Pre-solve (input validation)

| ID | Rule | Implementation | Violated → |
|---|---|---|---|
| H-18 | **Schema completeness** — all required fields present per spec field dictionaries | `validators.py` check 1 | Job skipped; surfaced through Pre-Route Communications |
| H-19 | **Coordinate bounds** — lat ∈ [41, 48], lon ∈ [−74, −67] | `validators.py` check 2 | Job excluded; flag `GEOCODE_OOB` |
| H-20 | **Referential integrity** — exception tech_or_slot matches existing tech; area_number exists | `validators.py` check 3 | Warning; run continues |
| H-21 | **Availability feasibility** — at least one (tech, vehicle, day) triple remains after exceptions | `validators.py` check 4 | Run aborted (empty schedule) |
| H-22 | **Duplicate ID detection** — no duplicate job_id or tech_id | `validators.py` check 5 | Run aborted |
| H-23 | **Job category validation** — job_category ∈ ALL_CATEGORIES (17 spec categories) | `validators.py` check 6 | Job skipped with communication record |

Note: spec §14.2 — "No standalone validation report is needed. The run should proceed, and any skipped jobs should be surfaced through the same communication flow using only Job # and what needs fixing."

---

## 2. Eligibility Filters

Eligibility filters **narrow the candidate space** before the scheduling loop runs.
They determine which (job, technician, vehicle, day) combinations the engine is allowed to consider.

| ID | Filter | Pipeline stage | What it produces |
|---|---|---|---|
| E-01 | **Queue-based exclusion** — remove Urgent and On Hold jobs | Stage 2: Exclude | Excluded jobs with reason `QUEUE_EXCLUDED` |
| E-02 | **Weekly exception application** — subtract unavailable tech-days (full-day blocks only in Initial build) | Stage 3: Apply Exceptions | Effective availability sets D_t |
| E-03 | **Vehicle work-type matching** — V-2 radiator-only, V-4 restricted categories | Eligibility check | Slot rejected; reason `VEHICLE_MISMATCH` |
| E-04 | **Route-shape evaluation** — cluster, corridor, Providence-assisted | Eligibility check | Slot rejected; reason `ROUTE_SHAPE` |
| E-05 | **Position constraint** — first-only / last-only job placement | Eligibility check | Slot rejected; reason `POSITION_CONFLICT` |
| E-06 | **Duplicate-address grouping** — group co-located jobs for route-shape evaluation | Stage 1 post-processing | Grouped set; Pre-Route Communication emitted if suspected duplicate |
| E-07 | **Special-route extraction** — pull radiator / NH overnight / helper jobs before normal fill | Stage 4: Reserve Special Routes | Reserved capacity consumed first |

### Eligibility checklist summary

A slot (j, t, k, d) is eligible only when **all rules pass**:

1. `TECH_AVAILABLE` — d ∈ D_t (tech available after exceptions)
2. `VEH_AVAILABLE` — d ∈ D_k (vehicle available)
3. `VEH_WORK_ELIGIBLE` — vehicle can carry this job category
4. `ROUTE_SHAPE_OK` — job fits the route geography
5. `POSITION_OK` — first-only / last-only constraint respected
6. `CAPACITY_OK` — current stops for (k, d) < route target
7. `TIME_OK` — current service for (t, d) + τ_j ≤ T_max × buffer
8. `ONE_VEH_PER_TECH` — tech t not using a different vehicle on day d
9. `ONE_TECH_PER_VEH` — vehicle k not assigned to a different tech on day d

Helper model: If any job on a route requires a helper, the entire route/day is marked `helper_required = yes`. The engine does not assign helpers by name (spec §5).

---

## 3. Weighted / Preference Logic

These rules **rank** feasible options — they never disallow an assignment, only make it more or less attractive.

### 3.1 Phase 1 — Queue-based decision-ladder ranking (spec §6.1)

| ID | Logic | Implementation | Effect |
|---|---|---|---|
| W-01 | **Winter decision ladder** | Priority → 2×-average Normal → AQ / Requested Scheduling (equal tier, better route wins) → Normal | Queue tier determines processing order |
| W-02 | **Summer decision ladder** | Priority → AQ / Requested Scheduling (equal tier, route quality decides) → Normal | Aging is **not** an active scoring factor in summer |
| W-03 | **Winter aging pressure** | Older jobs preferred within tier; 2×-average Normal can outrank AQ/RS | Must still make reasonable geographic sense |
| W-04 | **Closest-depot preference** | Best-fit slot selection, tiebreaker 1 | Among eligible slots, prefer the technician nearest the job |
| W-05 | **Lightest-day preference** | Best-fit slot selection, tiebreaker 2 | Among tied techs, prefer the day with least service time (natural load balancing) |

### 3.2 Phase 2 — Routing preferences

| ID | Logic | Implementation | Effect |
|---|---|---|---|
| W-06 | **Nearest-neighbour ordering** | NN algorithm | Always visits the closest unvisited stop next; produces compact routes |
| W-07 | **Geographic compactness** | Implicit via route-shape evaluation + NN ordering | Tighter clusters produce shorter routes |

### 3.3 Post-route preferences

| ID | Logic | Where applied | Notes |
|---|---|---|---|
| W-08 | **Area blending tolerance** | Inter-stop distance check | Neighbouring areas may mix when geography improves route quality; guidance, not hard wall (spec §6) |
| W-09 | **Standby usefulness ranking** | Post-route standby selection | Select the 2 lowest-priority jobs among otherwise acceptable route candidates (spec §7) |
| W-10 | **Geographic flexibility by queue** | Per spec Table 9 | Normal = normal geography only; Requested Scheduling = moderate; Priority / AQ = substantial weakening allowed |

---

## 4. Owner-Controlled Policy Inputs

Every item below is editable **without changing Python logic**.  
The table specifies where each input lives and what it controls.

### 4.1 Config file (JSON/YAML — version-controlled, developer-adjustable)

| Input | Parameter | Controls | Default guidance |
|---|---|---|---|
| Daily time budget | T_max | Caps travel + service time per route | Set to actual working hours |
| Phase 1 time buffer | T_max_phase1_fraction | Conservative fraction for service-only scheduling | 0.80 (leaves 20% headroom for travel) |
| Winter route target | winter_booked / standby_per_route | Stops per route | 4 booked + 2 standby (5th when backlog high) |
| Summer route target | summer_booked / standby_per_route | Stops per route | 3 booked + 2 standby |
| Cluster radius | R | Max distance depot → job | Domain-specific; start ~30 km |
| Inter-stop limit | r | Max distance between consecutive stops | Start ~15 km |
| Seasonal scoring config | decision-ladder weights | Job ranking within tiers | Configurable per spec §6.1 |
| Helpers available | helpers_available_default | Number of helpers per day | 2 (configurable) |
| Tech overload threshold | tech_overload_pct | Fires `TECH_OVERLOAD` flag | 0.90 (90% of available hours) |
| Vehicle bottleneck threshold | veh_bottleneck_days | Fires `VEH_BOTTLENECK` flag | 4 days at capacity |
| Standby threshold | weak_standby_threshold | Fires `WEAK_STANDBY` flag | 2 candidates per route |
| Shop departure time | shop_departure_time | Booking-window calculation | 07:00 |

### 4.2 Airtable (editable by owner at any time — no deployment needed)

| Input | Airtable table/field | Controls |
|---|---|---|
| Season | Weekly Context → Season | Winter vs summer decision-ladder selection |
| Include V-4 this week | Weekly Context → Include V-4 | Turns overflow slot on/off |
| Helper count | Weekly Context or config | Number of helpers available |
| Weekly exceptions | Weekly Exceptions table | Technician-day blocks (full-day only in Initial build) |
| Area rules / adjacency | Lookup / Rules table | Area naming, grouping, and adjacency |
| Vehicle restrictions | Lookup / Rules table | V-4 eligible categories, V-2 radiator-only |
| Radiator-hours formula | Airtable radiator-hours table | Active step values for radiator job time estimates |
| Holiday list | Weekly Context → Holiday List | Affects the week's schedule |
| 2×-average-wait flag | Candidate Jobs → 2x Average Wait Flag | Airtable-managed aging signal |
| Weekly exceptions (PTO, training) | Weekly Exceptions table | Shrinks effective capacity seen by Phase 1 (full-day blocks in Initial build) |
| Area rules / adjacency | Lookup / Rules table | Area naming, grouping, and adjacency rules |
| Vehicle restrictions | Lookup / Rules table | V-4 eligible categories, V-2 radiator-only |
| Radiator-hours formula | Airtable radiator-hours table | Active step values for radiator job time estimates |
| Candidate Jobs export | Jobs (ServiceM8 → Airtable sync) | The weekly input set (17 fields per spec Table 3) |

### 4.3 Override precedence

When the same parameter appears in both config and Airtable (e.g. per-vehicle capacity):
> **Airtable value wins.** This lets the owner make one-off adjustments without touching the config file. The config file provides sensible defaults.

---

## 5. Review Flags / Exception Outputs

The engine emits structured flags and exclusion reports with **every** weekly run, even when the plan is otherwise valid. These are the owner's primary trust and audit mechanism.

### 5.1 Review flags

Each flag has a severity level and a short, scannable code.

| Code | Severity | Trigger condition | What the owner should check |
|---|---|---|---|
| `DUP_ADDR` | INFO | Two or more jobs share the same address | Possible duplicate jobs; review before approving |
| `CROSS_AREA` | INFO | A route mixes jobs from ≥ 2 areas | May be optimal geographically — glance to confirm |
| `WEAK_STANDBY` | WARN | Fewer than 2 feasible standby jobs for a route | If a scheduled job drops, coverage is thin |
| `VEH_BOTTLENECK` | WARN | A vehicle is at 100% capacity on 4+ days | Little room for ad-hoc or emergency jobs |
| `TECH_OVERLOAD` | WARN | Technician's weekly service time > 90% of available hours | Overtime risk |
| `HELPER_TRAVEL` | WARN | Helper's home depot > R from primary tech's depot | Travel time for helper may be underestimated |
| `ROUTE_DROP` | WARN | Phase-1-scheduled job dropped during Phase 2 routing | Phase 1 / Phase 2 feasibility gap; consider lowering T_max buffer |
| `GEOCODE_OOB` | CRITICAL | Job coordinates outside New England bounding box | Geocoding error — job excluded, must be corrected in ServiceM8 |
| `NO_FEASIBLE` | CRITICAL | A (tech, vehicle, day) bundle has no feasible route at all | Entire bundle unserved; check exceptions or capacity |

> `SOLVER_TIMEOUT` is reserved for a future phase if a solver is introduced. Not used in Initial build.

### 5.2 Exclusion reason codes

For every job in the weekly pool that is **not** assigned, the engine emits exactly one reason code.

| Reason code | Explanation |
|---|---|
| `QUEUE_EXCLUDED` | Job queue is Urgent or On Hold — excluded from weekly engine |
| `UNKNOWN_QUEUE` | Job queue not in known eligible/excluded set |
| `NO_ELIGIBLE_TRIPLE` | No (tech, vehicle, day) triple passes all eligibility rules |
| `CAPACITY_FULL` | All eligible slots already at route-capacity target |
| `TIME_BUDGET` | Including this job would exceed T_max in every eligible slot |
| `VEHICLE_MISMATCH` | No available vehicle can carry this job category |
| `ROUTE_SHAPE` | Job does not fit acceptable route geography |
| `POSITION_CONFLICT` | First-only / last-only constraint cannot be satisfied |
| `ROUTE_DROP` | Job was scheduled by Phase 1 but dropped during Phase 2 routing (travel-time infeasibility) |
| `MISSING_GEOCODE` | Job could not be geocoded; skipped with communication record |
| `INVALID_CATEGORY` | Job category not in the 17 spec categories |

Note: `SKILL_MISMATCH`, `CLUSTER_RADIUS`, `PROHIBITED_PAIR`, `HELPER_UNAVAIL`, `STATUS_EXCLUDED`, and `ALREADY_ASSIGNED` from the pre-spec design are superseded. Skills are not modelled per-tech. Prohibited pairings are deferred. Helper is a route-level flag. Status is derived from queue. Upstream pre-filtering handles already-assigned jobs.

### 5.3 Output format

Per-run outputs:

- **Transcription calendar** — 5 weekday columns × 4 route rows (Tech 1, Tech 2, Tech 3, Van 4); job numbers only
- **Route grouping output** — assigned, standby, and anchor-hold jobs shown distinctly per route
- **Pre-Route Communications** — one Airtable row per issue (skipped jobs, weak routes, duplicates)
- **Route Communications** — one row per post-sync route-specific issue
- **`flags_{date}.json`** — array of `{code, severity, message, route_id?, tech_id?, job_id?}`
- **`exclusions_{date}.json`** — array of `{job_id, reason_code, detail}`
- **Route maps** — per day/route maps with labelled job pins, vehicle colour coding, route notes

`CRITICAL` flags are surfaced as bold-red banners at the top of the summary output so they cannot be overlooked.

---

## 6. Design Guidance

Use this classification as an **implementation rule** for every new feature or rule change:

1. **Hard constraints** produce explicit pass/fail. Implement as named eligibility rules in `eligibility.py` or feasibility checks in `nearest_neighbour.py`, or as pre-run checks in `validators.py`. Never silently relax.
2. **Eligibility filters** run before the scheduling loop. Implement in `eligibility.py`. Each filter maps to a named rule.
3. **Weighted / preference logic** stays parameterised. Coefficients and tiebreaker rankings live in config (§4.1) or Airtable (§4.2), never hard-coded.
4. **Review flags** are emitted even when the plan is valid. Add new flags in `flags.py`; assign a code, severity, and human-readable message.
5. **Owner-controlled policy** must not be hard-coded into the planning core. If the owner might want to change it, it belongs in config or Airtable.
6. **Exclusion reason codes** must cover every possible reason a job is not assigned. If a new exclusion path is added, a new reason code must be registered.

### Rule-change checklist

When adding or modifying a rule, answer these questions:

| Question | If yes → |
|---|---|
| Can a plan ever violate this rule? | It is a **hard constraint** (§1). Add as a named eligibility rule or feasibility check. |
| Does it narrow who/what can be combined? | It is an **eligibility filter** (§2). Update `eligibility.py`. |
| Does it make some options more attractive? | It is **weighted logic** (§3). Add a coefficient to config. |
| Should the owner be able to change it? | It is a **policy input** (§4). Put it in config or Airtable. |
| Should the owner see it after a run? | It is a **review flag or exclusion code** (§5). Register in `flags.py`. |