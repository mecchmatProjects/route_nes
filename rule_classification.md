# Rule Classification — NES Rules-Driven Weekly Dispatch Engine

> Companion to `main.tex` (system specification) and `technical_sketch.md` (implementation detail).
> This document classifies every scheduling and routing rule into five categories
> so the Python engine (`nes_dispatch/`) stays maintainable, testable, and auditable.

---

## 1. Hard Constraints

Hard constraints produce a binary **pass / fail** decision.  
A violated hard constraint means the assignment or route is **infeasible** — the engine must never output it.

### 1.1 Phase 1 — Scheduling (10 named eligibility rules)

| ID | Rule | Eligibility rule name | Violated → |
|---|---|---|---|
| H-01 | **Each job assigned at most once** across all (tech, vehicle, day) triples | (structural) | Duplicate assignment prevented |
| H-02 | **Technician available on day** after exceptions | `TECH_AVAILABLE` | Blocked; contributes to `NO_ELIGIBLE_TRIPLE` |
| H-03 | **Vehicle available on day** after exceptions | `VEH_AVAILABLE` | Blocked; contributes to `NO_ELIGIBLE_TRIPLE` |
| H-04 | **Technician skills cover job requirements** | `SKILL_MATCH` | Blocked; reason `SKILL_MISMATCH` |
| H-05 | **Vehicle capabilities cover route type** | `VEH_CAPABILITY` | Blocked; reason `VEHICLE_MISMATCH` |
| H-06 | **Job within cluster radius R of technician depot** | `WITHIN_RADIUS` | Blocked; reason `CLUSTER_RADIUS` |
| H-07 | **No prohibited technician–job pairing** | `NOT_PROHIBITED` | Blocked; reason `PROHIBITED_PAIR` |
| H-08 | **Vehicle capacity per day** — stops ≤ Q_k | `CAPACITY_OK` | Excess job excluded; reason `CAPACITY_FULL` |
| H-09 | **Service-time budget** — total per day ≤ T_max × buffer | `TIME_OK` | Excess job excluded; reason `TIME_BUDGET` |
| H-10 | **One vehicle per technician per day** | `ONE_VEH_PER_TECH` | Vehicle re-assignment prevented |
| H-11 | **One technician per vehicle per day** | `ONE_TECH_PER_VEH` | Tech re-assignment prevented |
| H-12 | **Helper required for two-man jobs** — exactly one helper ≠ primary | (helper pass) | Job excluded if no helper; reason `HELPER_UNAVAIL` |

### 1.2 Phase 2 — Routing (nearest-neighbour feasibility checks)

| ID | Rule | Implementation | Violated → |
|---|---|---|---|
| H-13 | **Depart from and return to depot** | NN algorithm structure | Route structurally invalid |
| H-14 | **No stop visited more than once** | NN algorithm structure | Duplicate visit prevented |
| H-15 | **Total travel + service time ≤ T_max** | Feasibility verification | Last-added job dropped; reason `ROUTE_DROP` |
| H-16 | **Stops ≤ Q_k** (vehicle capacity) | Feasibility verification | Excess stop dropped |
| H-17 | **Every stop within radius R of depot** | Enforced by Phase 1 eligibility (`WITHIN_RADIUS`) | Should not occur; flag `GEOCODE_OOB` if violated |

### 1.3 Pre-solve (input validation)

| ID | Rule | Implementation | Violated → |
|---|---|---|---|
| H-18 | **Schema completeness** — all required CSV columns present and non-null | `validators.py` check 1 | Run aborted with consolidated error |
| H-19 | **Coordinate bounds** — lat ∈ [41, 48], lon ∈ [−74, −67] | `validators.py` check 2 | Job excluded; flag `GEOCODE_OOB` |
| H-20 | **Referential integrity** — exception scope_id matches existing tech/vehicle; area_id exists | `validators.py` check 3 | Run aborted |
| H-21 | **Availability feasibility** — at least one (tech, vehicle, day) triple remains after exceptions | `validators.py` check 4 | Run aborted (empty schedule) |
| H-22 | **Duplicate ID detection** — no duplicate job_id, tech_id, or vehicle_id | `validators.py` check 5 | Run aborted |
| H-23 | **Config schema validation** — all params present, positive, within bounds | `validators.py` check 6 | Run aborted |

---

## 2. Eligibility Filters

Eligibility filters **narrow the candidate space** before the scheduling loop runs.
They determine which (job, technician, vehicle, day) combinations the engine is allowed to consider.

| ID | Filter | Pipeline stage | What it produces |
|---|---|---|---|
| E-01 | **Candidate pool import** — accept only jobs with `status = candidate` | Stage 1: Load & Validate | Clean job set J |
| E-02 | **Status exclusion** — remove `excluded`, `cancelled`, `assigned` jobs | Stage 2: Exclude | Excluded jobs with reason `STATUS_EXCLUDED` or `ALREADY_ASSIGNED` |
| E-03 | **Weekly exception application** — subtract unavailable tech-days and vehicle-days | Stage 3: Apply Exceptions | Effective availability sets D_t, D_k |
| E-04 | **Skill matching** — skill_t ⊇ req(j) | Eligibility check | Slot rejected; reason `SKILL_MISMATCH` |
| E-05 | **Vehicle capability matching** — cap_k ⊇ ρ_j | Eligibility check | Slot rejected; reason `VEHICLE_MISMATCH` |
| E-06 | **Cluster radius filter** — haversine(depot, job) ≤ R | Eligibility check | Slot rejected; reason `CLUSTER_RADIUS` |
| E-07 | **Prohibited pairing filter** — (tech, job) pair on exclusion list | Eligibility check | Slot rejected; reason `PROHIBITED_PAIR` |
| E-08 | **Helper eligibility** — eligible helper techs for j ∈ J^H (available, skilled, within reach) | Helper assignment pass | Determines which techs may serve as helpers |
| E-09 | **Duplicate-address grouping** — group co-located jobs for route-shape evaluation | Stage 1 post-processing | Grouped set; flag `DUP_ADDR` emitted |
| E-10 | **Special-route extraction** — pull radiator / NH overnight / helper jobs before normal fill | Stage 4: Reserve Special Routes | Reserved capacity consumed first |

### Eligibility checklist summary

A slot (j, t, k, d) is eligible only when **all 10 rules pass**:

1. `TECH_AVAILABLE` — d ∈ D_t (tech available after exceptions)
2. `VEH_AVAILABLE` — d ∈ D_k (vehicle available after exceptions)
3. `SKILL_MATCH` — skill_t ⊇ req(j)
4. `VEH_CAPABILITY` — cap_k ⊇ ρ_j
5. `WITHIN_RADIUS` — haversine(depot_t, job_j) ≤ R
6. `NOT_PROHIBITED` — (t, j) not in prohibited-pairing list
7. `CAPACITY_OK` — current stops for (k, d) < Q_k
8. `TIME_OK` — current service for (t, d) + τ_j ≤ T_max × buffer
9. `ONE_VEH_PER_TECH` — tech t not using a different vehicle on day d
10. `ONE_TECH_PER_VEH` — vehicle k not assigned to a different tech on day d

Helper eligibility for j ∈ J^H requires conditions 1, 3, 5 above (vehicle-independent), plus helper ≠ primary and helper has time remaining.

---

## 3. Weighted / Preference Logic

These rules **rank** feasible options — they never disallow an assignment, only make it more or less attractive.

### 3.1 Phase 1 — Scoring and slot-selection preferences

| ID | Logic | Implementation | Effect |
|---|---|---|---|
| W-01 | **Composite priority score** | score_j = w_g·geo + w_f·fair + w_a·age + w_r·readiness | Higher-scoring jobs are considered first in the greedy loop |
| W-02 | **Seasonal weight profile** | (w_g, w_f, w_a, w_r) shift by season | Geography-dominant Mar–Sep; fairness-dominant Oct–Feb |
| W-03 | **Aging pressure** | w_a · α_j component in score | Jobs waiting longer rise in priority; soft, not absolute |
| W-04 | **Closest-depot preference** | Best-fit slot selection, tiebreaker 1 | Among eligible slots, prefer the technician nearest the job |
| W-05 | **Lightest-day preference** | Best-fit slot selection, tiebreaker 2 | Among tied techs, prefer the day with least service time (natural load balancing) |
| W-06 | **Cheapest-vehicle preference** | Best-fit slot selection, tiebreaker 3 | Among tied days, prefer the vehicle with lower cost rate c_k |

### 3.2 Phase 2 — Routing preferences

| ID | Logic | Implementation | Effect |
|---|---|---|---|
| W-07 | **Nearest-neighbour ordering** | NN algorithm | Always visits the closest unvisited stop next; produces compact routes |
| W-08 | **Geographic compactness** | Implicit via R, r constraints + NN ordering | Tighter clusters produce shorter routes |

### 3.3 Post-route preferences

| ID | Logic | Where applied | Notes |
|---|---|---|---|
| W-09 | **Area blending tolerance** | Inter-stop distance check | Neighbouring areas may mix when geography improves route quality; guidance, not hard wall |
| W-10 | **Standby usefulness ranking** | Post-route standby selection | Prefer backups that are plausible substitutes (close, eligible, similar service time) |
| W-11 | **Area readiness support** | Post-route readiness computation | Prefer proposals that produce credible coverage; should not override route sanity |

---

## 4. Owner-Controlled Policy Inputs

Every item below is editable **without changing Python logic**.  
The table specifies where each input lives and what it controls.

### 4.1 Config file (JSON/YAML — version-controlled, developer-adjustable)

| Input | Parameter | Controls | Default guidance |
|---|---|---|---|
| Daily time budget | T_max | Caps travel + service time per route | Set to actual working hours; Phase 1 uses 80% buffer |
| Phase 1 time buffer | T_max_phase1_fraction | Conservative fraction for service-only scheduling | 0.80 (leaves 20% headroom for travel) |
| Global max stops | P | Upper bound on stops per route | 14 (match largest vehicle) |
| Cluster radius | R | Max distance depot → job | Domain-specific; start ~30 km |
| Inter-stop limit | r | Max distance between consecutive stops | Start ~15 km |
| Seasonal weight profiles | (w_g, w_f, w_a, w_r) × 2 | Job scoring formula; two profiles (summer / winter) | Geography-dominant Mar–Sep; fairness-dominant Oct–Feb |
| Tech overload threshold | tech_overload_pct | Fires `TECH_OVERLOAD` flag | 0.90 (90% of available hours) |
| Vehicle bottleneck threshold | veh_bottleneck_days | Fires `VEH_BOTTLENECK` flag | 4 days at capacity |
| Standby threshold | weak_standby_threshold | Fires `WEAK_STANDBY` flag | 2 candidates per route |

### 4.2 Airtable (editable by owner at any time — no deployment needed)

| Input | Airtable table | Controls |
|---|---|---|
| Vehicle roster & capability tags | Vehicles | Which vehicles exist and what they can do (cap_k) |
| Vehicle availability days | Vehicles | Base weekly schedule per vehicle (D_k before exceptions) |
| Vehicle speed / cost / capacity overrides | Vehicles | Per-vehicle v_k, c_k, Q_k |
| Technician roster & skills | Technicians | Who is available, what they can do (skill_t) |
| Technician home-depot coordinates | Technicians | Start locations (y_t, x_t) for clustering |
| Weekly exceptions (PTO, maintenance) | Exceptions | Shrinks effective capacity seen by Phase 1 |
| Prohibited technician–job pairings | Pairings | Exclusion list feeding eligibility rule `NOT_PROHIBITED` |
| Geographic area definitions | Areas | Area set A and area-to-boundary mapping |
| Special-route flags | Jobs (or Overrides) | Which jobs require radiator / NH overnight / helper handling |
| Job candidate pool | Jobs (ServiceM8 sync) | The weekly input set J |

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

> `SOLVER_TIMEOUT` is reserved for future Version 2 if a solver is introduced. Not used in V1.

### 5.2 Exclusion reason codes

For every job in the weekly pool that is **not** assigned, the engine emits exactly one reason code.

| Reason code | Explanation |
|---|---|
| `ALREADY_ASSIGNED` | Job was assigned in a prior run and not reset |
| `STATUS_EXCLUDED` | Job status is `excluded` or `cancelled` in ServiceM8 |
| `NO_ELIGIBLE_TRIPLE` | No (tech, vehicle, day) triple passes all 10 eligibility rules |
| `CAPACITY_FULL` | All eligible slots already at vehicle capacity Q_k |
| `TIME_BUDGET` | Including this job would exceed T_max in every eligible slot |
| `CLUSTER_RADIUS` | Job outside cluster radius R from every available tech depot |
| `SKILL_MISMATCH` | No available technician has the required skills |
| `VEHICLE_MISMATCH` | No available vehicle has the required capability tags |
| `HELPER_UNAVAIL` | Job requires helper (h_j = 1) but no second tech eligible on any feasible day |
| `PROHIBITED_PAIR` | All eligible technicians are on the prohibited-pairing list |
| `ROUTE_DROP` | Job was scheduled by Phase 1 but dropped during Phase 2 routing (travel-time infeasibility) |

### 5.3 Output format

Two JSON files per run:

- **`flags_{date}.json`** — array of `{code, severity, message, route_id?, tech_id?, job_id?}`
- **`exclusions_{date}.json`** — array of `{job_id, reason_code, detail}`

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