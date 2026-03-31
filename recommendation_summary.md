# Final Recommendation Summary

> Companion to `main.tex` and `technical_sketch.md`.
> Purpose: decision-ready brief for the project owner before committing to a build.

---

## 1  Recommended Initial Build Scope

The Initial build should deliver the **minimum pipeline that replaces manual weekly dispatch
with a reliable draft transcription calendar Ryan can trust and transcribe into ServiceM8**.
Anything beyond this scope belongs in a later phase.

### What is IN the Initial Build

| Component | Deliverable | Why it matters |
|---|---|---|
| **Data layer** | `loaders.py` + `validators.py` — load four-payload contract (Candidate Jobs, Weekly Context, Weekly Exceptions, Lookup/Rules Data) into typed dataclasses, run pre-run validation. Skip jobs with missing geocodes rather than abort. | Garbage-in protection. Every downstream decision depends on clean inputs. |
| **Phase 1 — Queue-based decision-ladder scheduling** | Seasonal ranking (winter: Priority → 2×-average Normal → AQ/RS → Normal; summer: Priority → AQ/RS → Normal), eligibility checks (VEH_WORK_ELIGIBLE, ROUTE_SHAPE_OK, POSITION_OK, etc.), best-fit slot selection. | Core value: decide *which* jobs happen on *which* day, with *whom* and *what vehicle*. Every assignment traceable to a named rule. |
| **Helper-required flagging** | Per route/day `helper_required = yes/no` flag. If any job on a route needs a helper, the entire route/day is helper-required. Configurable helper count (default 2). | Handles real-world two-person jobs. Does not assign helpers by name (spec §5). |
| **Phase 2 — Nearest-neighbour routing** | NN stop ordering + feasibility verification (time, capacity). Drop and re-sequence if constraints violated. | Turns an abstract schedule into a drivable stop sequence. |
| **Post-processing** | Standby ranking (2 per route), anchor-hold identification, Pre-Route Communications, Route Communications, review flags, exclusion report. | Owner sees structured review artifacts before approving the plan. |
| **Callable workflows** | Weekly Run, Replacement Job (up to 2 unranked candidates), Replacement Route (rebuild one day). | Covers standard weekly planning plus day-damage recovery. |
| **Config file** | Single `config.json` with T_max, route targets (winter 4+2, summer 3+2), seasonal weights, booking-window parameters, workload thresholds. | Tunable without code changes; version-controlled for reproducibility. |
| **Output artefacts** | Transcription calendar (5×4 grid, job numbers only), route grouping, route flags, Pre-Route/Route Communications, per-route maps, exclusion report. | Transcription calendar is the primary deliverable; communications provide trust layer. |
| **Map rendering** | Per-route PNG maps with labelled job pins, vehicle colour coding, route notes. | Visual review artefact; lets Ryan confirm geographic sanity at a glance. |
| **Live-week testing** | Real upcoming live scheduling week. Thursday deadline. Two-week-failure pause rule. | Proves the pipeline works on real data before it becomes the production workflow. |

### What is OUT of the Initial Build

| Deferred feature | Reason |
|---|---|
| **Assigning helpers by name** | Spec says yes/no flag only; named assignment deferred. |
| **Revision-code logic** | Deferred until testing reveals real failure modes. |
| **Scheduling Preferences detail source** | Queue stays; exact source of preference text pending Amy. |
| **Radiator module tuning** | Formulas live in Airtable; Ryan still needs to set first real values. |
| **2×-average-wait trigger source** | Airtable will supply the flag; implementation TBD. |
| **Area Readiness final scope** | Optional / pending Amy. |
| **Generic freeform communication button** | Standard buttons sufficient for Initial build. |
| **Iterative Phase 1 ↔ Phase 2 feedback** | Desirable, but doubles pipeline complexity. Conservative 80% T_max buffer instead. |
| **2-opt route improvement** | Good first post-Initial enhancement. |
| **TSP/VRP solver** | Not needed until route quality becomes a measurable problem. |
| **MILP scheduling** | Drop-in replacement if greedy proves insufficient. |
| **Appointment-time optimisation** | Requires customer preference data not currently available. |
| **Real-time traffic integration** | Google Maps API for static planning is sufficient. |
| **Multi-week rolling horizon** | Needs historical job-outcome data. |

### Initial build success criteria (spec §14.4)

1. Testing uses the real upcoming live scheduling week.
2. Ryan may start as early as Monday; freelancer may revise up to Thursday.
3. If output is not usable by Thursday, Ryan reverts to manual for that week.
4. Most live weeks should be approved by Ryan with no changes.
5. One imperfect route does not fail the entire week, but routine rebuilding = failure.
6. If two live weeks fail, the project pauses automatically for review.
7. A re-run with identical inputs + config produces identical outputs (fully deterministic).

---

## 2  Biggest Pitfall to Avoid

**Skipping the decision-ladder layer and jumping straight to route optimisation.**

This is the single highest-risk mistake because:

- **Phase 1 output defines Phase 2 input.** If the scheduling assignment is wrong
  (infeasible triples, over-committed days, eligibility violations), no amount of
  clever routing will fix it — every route will be broken or sub-optimal.

- **Phase 1 is where the owner's policy levers live.** Season, queue priorities,
  vehicle assignments, exception blocks, V-4 toggle, helper counts — all feed
  into the decision ladder and eligibility checks. If these are not wired
  correctly, the engine produces plans the owner will consistently override,
  destroying trust in the tool.

- **Phase 2 is a well-understood problem.** Nearest-neighbour is a reliable
  placeholder; 2-opt or OR-Tools can upgrade it later. The reverse is not true —
  there is no off-the-shelf "weekly service scheduling" that encodes NES-specific
  queue-based decision ladders, vehicle/tech pairing, area rules, and seasonal weighting.

**Concrete recommendation:** get Phase 1 producing correct, policy-compliant
schedule assignments on real data — verified by Ryan — before investing
in route-quality improvements. Nearest-neighbour is sufficient for the Initial build.

### Secondary pitfalls (worth watching)

| Pitfall | Mitigation |
|---|---|
| **Trusting geocodes blindly** | Skip jobs with missing/bad geocodes rather than abort. A single wrong coordinate puts a job in the wrong cluster and corrupts the entire route. |
| **Over-tuning parameters before data is stable** | Lock weights and thresholds at documented defaults. Tune only after 4+ weeks of real live-week runs with owner feedback. |
| **Skipping the exclusion report** | The exclusion report is the owner's trust mechanism. If a job is dropped with no explanation, the owner assumes the engine is broken. Always emit a reason code (QUEUE_EXCLUDED, ROUTE_SHAPE, POSITION_CONFLICT, MISSING_GEOCODE, INVALID_CATEGORY). |
| **Making Airtable schema changes without versioning** | Any field rename or table restructure silently breaks `loaders.py`. Pin expected column names in a schema constant; fail fast on mismatch. The four-payload contract is the binding interface. |

---

## 3  Remaining Open Questions

The Build Spec v7 and Clarification Addendum resolved most of the original
questions. The items below are either **still open** or **partially answered**.

### 3.1  Data & integrations

| # | Question | Status |
|---|---|---|
| 1 | **Airtable schema** | ✅ ANSWERED — Four-payload contract defined in spec Tables 3–6. Field dictionaries in addendum. |
| 2 | **ServiceM8 → Airtable sync** | ⚠️ PARTIALLY — spec says Amy manages the Airtable export; sync mechanism/frequency still unspecified. |
| 3 | **Coordinate system** | ✅ ANSWERED — Google Maps lat/lon (WGS-84). Jobs with missing geocodes are gracefully skipped. |
| 4 | **Vehicle speed / cost values** | ✅ SUPERSEDED — Google Maps Distance Matrix provides real travel times. Per-vehicle cost model not part of spec. |

### 3.2  Business rules

| # | Question | Status |
|---|---|---|
| 5 | **T_max (daily time budget)** | ⚠️ PARTIALLY — spec defines route capacity (winter 4+2, summer 3+2 jobs) and booking windows, but exact wall-clock T_max not stated. Config parameter. |
| 6 | **Seasonal periods** | ✅ ANSWERED — `season` field in Weekly Context payload. Owner selects per-week. |
| 7 | **Prohibited pairings** | ✅ SUPERSEDED — spec uses Weekly Exceptions (full tech-day blocks) instead of pairwise prohibitions. |
| 8 | **Helper-needed flag source** | ✅ ANSWERED — derived from `job_category` (17-category table). Two-Man Work = helper-required. Route-level flag, no named assignment. |
| 9 | **Output format preference** | ✅ ANSWERED — Transcription calendar (5×4 grid), Pre-Route / Route Communications, per-route maps, exclusion report. Review in-browser via Airtable interface. |

### 3.3  Operational

| # | Question | Status |
|---|---|---|
| 10 | **Where does the engine run?** | ⚠️ OPEN — spec describes live-week testing but not deployment target. |
| 11 | **Weekly cadence** | ✅ ANSWERED — Weekly Run is the standard workflow. Ryan may start Monday; freelancer revises up to Thursday. Multiple trial runs expected. |
| 12 | **Who installs/updates?** | ⚠️ PARTIALLY — spec §10 gives ownership split (Freelancer / Amy-Airtable / Shared). Installation mechanics still TBD. |

### Remaining blockers

| # | New question | Impact if unanswered |
|---|---|---|
| 13 | **2×-average-wait trigger source.** Spec says Airtable supplies the flag, but the exact field/formula is unspecified. | Winter ladder depends on this flag to elevate long-waiting Normal jobs. |
| 14 | **Radiator-hours table values.** Ryan needs to set initial values before the engine can plan Radiator-category jobs. | Radiator jobs currently have no planned hours. |
| 15 | **Area Readiness scope.** Spec marks this as optional / pending Amy. | If active, it adds an adjacency/grouping constraint to route shaping. |

---

*Document generated from the NES Build Spec v7, the Clarification Addendum,
`main.tex`, and the implementation sketch in `technical_sketch.md`.*
