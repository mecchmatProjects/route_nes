# Rule Classification — NES Two-Layer Weekly Dispatch Engine

> Companion to `main.tex` (mathematical model) and `technical_sketch.md` (implementation detail).
> This document classifies every scheduling and routing rule into five categories
> so the Python engine (`nes_dispatch/`) stays maintainable, testable, and auditable.

---

## 1. Hard Constraints

Hard constraints produce a binary **pass / fail** decision.  
A violated hard constraint means the assignment or route is **infeasible** — the engine must never output it.

### 1.1 Layer 1 — Scheduling (MILP constraints S1–S11)

| ID | Rule | Math reference | Violated → |
|---|---|---|---|
| H-01 | **Each job assigned at most once** across all (tech, vehicle, day) triples | S1: Σ y ≤ 1 | Duplicate assignment prevented |
| H-02 | **Eligibility gate** — assignment only where e[j,t,k,d] = 1 | S2: y ≤ e | Blocked; reason `NO_ELIGIBLE_TRIPLE` |
| H-03 | **Vehicle capacity per day** — stops ≤ Q_k | S3: Σ y ≤ Q_k | Excess job excluded; reason `CAPACITY_FULL` |
| H-04 | **Service-time budget** — Σ τ_j · y ≤ T_max | S4 | Excess job excluded; reason `TIME_BUDGET` |
| H-05 | **One vehicle per technician per day** | S5–S6: Σ_k z ≤ 1 | Vehicle re-assignment prevented |
| H-06 | **One technician per vehicle per day** | S8: Σ_t z ≤ 1 | Tech re-assignment prevented |
| H-07 | **Helper required for two-man jobs** — scheduled helper job gets exactly one helper | S9: Σ_t y^H = Σ y | Job excluded if no helper available; reason `HELPER_UNAVAIL` |
| H-08 | **Helper ≠ primary technician** | S10: y^H + Σ_k y ≤ 1 | Same-person assignment prevented |
| H-09 | **Helper eligibility** — y^H ≤ e^H | S11 | Ineligible helper blocked |

### 1.2 Layer 2 — Routing (MILP / heuristic constraints)

| ID | Rule | Math reference | Violated → |
|---|---|---|---|
| H-10 | **Depart from and return to depot** | Eq. depart / return | Route is structurally invalid |
| H-11 | **No node visited more than once** | Eq. in-once / out-once | Duplicate visit prevented |
| H-12 | **Flow conservation** — in-degree = out-degree at every node | Eq. flow | Route is disconnected |
| H-13 | **Total travel + service time ≤ T_max** | Eq. time | Excess job dropped; reason `ROUTE_DROP` |
| H-14 | **Stops ≤ Q_k** (vehicle capacity) | Eq. capacity | Excess stop dropped |
| H-15 | **Cluster radius** — every stop within R of depot | Eq. cluster | Arc pruned pre-solve |
| H-16 | **Inter-stop distance limit** — d(i,j) ≤ r | Eq. interstop | Arc pruned pre-solve |
| H-17 | **Subtour elimination** (MTZ) | Eq. mtz | Disconnected sub-loops prevented |

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

Eligibility filters **narrow the candidate space** before the optimiser runs.  
They are not pass/fail on the final output — they determine which combinations the solver is allowed to consider.

| ID | Filter | Pipeline stage | What it produces |
|---|---|---|---|
| E-01 | **Candidate pool import** — accept only jobs with `status = candidate` | Stage 1: Load & Normalise | Clean job set J |
| E-02 | **Status exclusion** — remove `excluded`, `cancelled`, `assigned` jobs | Stage 2: Exclude | Excluded jobs with reason `STATUS_EXCLUDED` or `ALREADY_ASSIGNED` |
| E-03 | **Weekly exception application** — subtract unavailable tech-days and vehicle-days | Stage 3: Apply Exceptions | Effective availability sets D_t, D_k |
| E-04 | **Skill matching** — skill_t ⊇ req(j) | Eligibility matrix build | e[j,t,k,d] = 0 where skills don't match; reason `SKILL_MISMATCH` |
| E-05 | **Vehicle capability matching** — cap_k ⊇ ρ_j | Eligibility matrix build | e[j,t,k,d] = 0 where capability fails; reason `VEHICLE_MISMATCH` |
| E-06 | **Cluster radius filter** — haversine(depot, job) ≤ R | Eligibility matrix build | e[j,t,k,d] = 0 where too far; reason `CLUSTER_RADIUS` |
| E-07 | **Prohibited pairing filter** — (tech, job) pair on exclusion list | Eligibility matrix build | e[j,t,k,d] = 0; reason `PROHIBITED_PAIR` |
| E-08 | **Helper eligibility matrix** — build e^H[j,t,d] for j ∈ J^H | Eligibility matrix build | Determines which techs may serve as helpers |
| E-09 | **Duplicate-address grouping** — group co-located jobs for route-shape evaluation | Stage 1 post-processing | Grouped set; flag `DUP_ADDR` emitted |
| E-10 | **Special-route extraction** — pull radiator / NH overnight / helper jobs before normal fill | Stage 4: Reserve Special Routes | Reserved capacity consumed first |

### Eligibility matrix summary

The full eligibility parameter e[j,t,k,d] = 1 requires **all** of:

1. d ∈ D_t (tech available after exceptions)
2. d ∈ D_k (vehicle available after exceptions)
3. skill_t ⊇ req(j)
4. cap_k ⊇ ρ_j
5. haversine(depot_t, job_j) ≤ R
6. (t, j) not in prohibited-pairing list

Helper eligibility e^H[j,t,d] = 1 requires conditions 1, 3, 5 above (vehicle-independent).

---

## 3. Weighted / Preference Logic

These rules **rank** feasible options — they never disallow an assignment, only make it more or less attractive to the solver.

### 3.1 Layer 1 — Scheduling objective components

| ID | Logic | Math expression | Effect |
|---|---|---|---|
| W-01 | **Job value maximisation** | Σ w_j · y[j,t,k,d] | Higher-value jobs preferred for assignment |
| W-02 | **Workload uniformity penalty** | −λ · Σ(s⁺ + s⁻) | Balanced daily loads across technicians; controlled by λ |
| W-03 | **Seasonal scoring formula** | score_j = w_g·geo + w_f·fair + w_a·age + w_r·readiness | Shifts priority between geography (Mar–Sep) and fairness (Oct–Feb) |
| W-04 | **Aging pressure** | w_a · α_j component in score | Jobs waiting longer get higher weight; soft, not absolute |

### 3.2 Layer 2 — Routing objective components

| ID | Logic | Math expression | Effect |
|---|---|---|---|
| W-05 | **Route score maximisation** | Σ w_j · x[i,j] | Prefer visiting higher-value stops |
| W-06 | **Travel cost minimisation** | −Σ c_k · d[i,j] · x[i,j] | Shorter routes preferred; cost is vehicle-dependent |
| W-07 | **Geographic compactness** | Implicit via R, r constraints + cost term | Tighter clusters produce shorter, cheaper routes |

### 3.3 Post-optimisation preferences

| ID | Logic | Where applied | Notes |
|---|---|---|---|
| W-08 | **Area blending tolerance** | Clustering (Algorithm 1) | Neighbouring areas may mix when geography improves route quality; guidance, not hard wall |
| W-09 | **Standby usefulness ranking** | Post-route standby selection | Prefer backups that are plausible substitutes (close, eligible, similar service time) |
| W-10 | **Area readiness support** | Post-route readiness computation | Prefer proposals that produce credible coverage; should not override route sanity |

---

## 4. Owner-Controlled Policy Inputs

Every item below is editable **without changing Python logic**.  
The table specifies where each input lives and what it controls.

### 4.1 Config file (JSON/YAML — version-controlled, developer-adjustable)

| Input | Parameter | Controls | Default guidance |
|---|---|---|---|
| Workload-balance weight | λ | Trade-off: job value vs load equality (Eq. sched_obj) | Start at 100; increase if dispatchers complain about uneven days |
| Daily time budget | T_max | Caps travel + service time per route (both layers) | Set to 80% of real day length to buffer for L1→L2 feasibility gap |
| Global max stops | P | Upper bound on stops per route | 14 (match largest vehicle) |
| Cluster radius | R | Max distance depot → job | Domain-specific; start ~50 km |
| Inter-stop limit | r | Max distance between consecutive stops | Start ~15 km |
| Seasonal weight profiles | (w_g, w_f, w_a, w_r) × 2 | Job scoring formula; two profiles (summer / winter) | Geography-dominant Mar–Sep; fairness-dominant Oct–Feb |
| Solver timeout | seconds | Max time before solver returns best-found solution | 120 s |
| SA hyper-parameters | T_start, α, K | Simulated Annealing tuning | Lock at documented defaults until 4+ weeks of real data |
| Random seed | integer | Deterministic SA runs for reproducibility | Any fixed integer |

### 4.2 Airtable (editable by owner at any time — no deployment needed)

| Input | Airtable table | Controls |
|---|---|---|
| Vehicle roster & capability tags | Vehicles | Which vehicles exist and what they can do (cap_k) |
| Vehicle availability days | Vehicles | Base weekly schedule per vehicle (D_k before exceptions) |
| Vehicle speed / cost / capacity overrides | Vehicles | Per-vehicle v_k, c_k, Q_k |
| Technician roster & skills | Technicians | Who is available, what they can do (skill_t) |
| Technician home-depot coordinates | Technicians | Start locations (y_t, x_t) for clustering |
| Weekly exceptions (PTO, maintenance) | Exceptions | Shrinks effective capacity seen by Layer 1 |
| Prohibited technician–job pairings | Pairings | Exclusion list feeding eligibility filter E-07 |
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
| `ROUTE_DROP` | WARN | Layer-1-scheduled job(s) dropped during Layer-2 routing | L1/L2 feasibility gap; consider lowering T_max buffer |
| `GEOCODE_OOB` | CRITICAL | Job coordinates outside New England bounding box | Geocoding error — job excluded, must be corrected in ServiceM8 |
| `NO_FEASIBLE` | CRITICAL | A (tech, vehicle, day) bundle has no feasible route at all | Entire bundle unserved; check exceptions or capacity |
| `SOLVER_TIMEOUT` | WARN | Solver hit time limit before proving optimality | Solution is feasible but may not be optimal |

### 5.2 Exclusion reason codes

For every job in the weekly pool that is **not** assigned, the engine emits exactly one reason code.

| Reason code | Explanation |
|---|---|
| `ALREADY_ASSIGNED` | Job was assigned in a prior run and not reset |
| `STATUS_EXCLUDED` | Job status is `excluded` or `cancelled` in ServiceM8 |
| `NO_ELIGIBLE_TRIPLE` | No (tech, vehicle, day) triple satisfies all eligibility conditions — e[j,t,k,d] = 0 everywhere |
| `CAPACITY_FULL` | All eligible slots already at vehicle capacity Q_k |
| `TIME_BUDGET` | Including this job would exceed T_max in every eligible slot |
| `CLUSTER_RADIUS` | Job outside cluster radius R from every available tech depot |
| `SKILL_MISMATCH` | No available technician has the required skills |
| `VEHICLE_MISMATCH` | No available vehicle has the required capability tags |
| `HELPER_UNAVAIL` | Job requires helper (h_j = 1) but no second tech eligible on any feasible day |
| `PROHIBITED_PAIR` | All eligible technicians are on the prohibited-pairing list |
| `ROUTE_DROP` | Job was scheduled by Layer 1 but dropped during Layer 2 routing (travel-time infeasibility) |

### 5.3 Output format

Two JSON files per run:

- **`flags_{date}.json`** — array of `{code, severity, message, route_id?, tech_id?, job_id?}`
- **`exclusions_{date}.json`** — array of `{job_id, reason_code, detail}`

`CRITICAL` flags are surfaced as bold-red banners at the top of the summary output so they cannot be overlooked.

---

## 6. Design Guidance

Use this classification as an **implementation rule** for every new feature or rule change:

1. **Hard constraints** produce explicit pass/fail. Implement in the MILP formulation or `validators.py`. Never silently relax.
2. **Eligibility filters** run before the solver. Implement in `eligibility.py`. Output feeds the e[j,t,k,d] matrix.
3. **Weighted / preference logic** stays parameterised. Coefficients live in config (§4.1) or Airtable (§4.2), never hard-coded.
4. **Review flags** are emitted even when the plan is valid. Add new flags in `flags.py`; assign a code, severity, and human-readable message.
5. **Owner-controlled policy** must not be hard-coded into the planning core. If the owner might want to change it, it belongs in config or Airtable.
6. **Exclusion reason codes** must cover every possible reason a job is not assigned. If a new exclusion path is added, a new reason code must be registered.

### Rule-change checklist

When adding or modifying a rule, answer these questions:

| Question | If yes → |
|---|---|
| Can a plan ever violate this rule? | It is a **hard constraint** (§1). Add to MILP or validator. |
| Does it narrow who/what can be combined? | It is an **eligibility filter** (§2). Update `eligibility.py`. |
| Does it make some options more attractive? | It is **weighted logic** (§3). Add a coefficient to config. |
| Should the owner be able to change it? | It is a **policy input** (§4). Put it in config or Airtable. |
| Should the owner see it after a run? | It is a **review flag or exclusion code** (§5). Register in `flags.py`. |