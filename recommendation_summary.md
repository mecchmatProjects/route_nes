# Final Recommendation Summary

> Companion to `main.tex` and `technical_sketch.md`.
> Purpose: decision-ready brief for the project owner before committing to a build.

---

## 1  Recommended Version 1 Scope

Version 1 should deliver the **minimum pipeline that replaces manual weekly dispatch
with a reviewable, reproducible plan**. Anything beyond this scope belongs in Version 2.

### What is IN Version 1

| Component | Deliverable | Why it matters |
|---|---|---|
| **Data layer** | `loaders.py` + `validators.py` — pull jobs / techs / vehicles / exceptions from Airtable & ServiceM8 into typed dataclasses, run the 6 pre-run validation checks. | Garbage-in protection. Every downstream decision depends on clean inputs. |
| **Phase 1 — Rules-based scheduling** | Score-sort-assign greedy loop: composite priority scoring, 10 named eligibility rules, best-fit slot selection (closest depot → lightest day → cheapest vehicle). | Core value: decide *which* jobs happen on *which* day, with *whom* and *what vehicle*. Every assignment traceable to a named rule. |
| **Helper-job modelling** | Secondary assignment pass for two-man jobs (h_j = 1): find a second technician ≠ primary who is available, skilled, and within reach. | Handles real-world two-person jobs without deferring to Version 2. |
| **Phase 2 — Nearest-neighbour routing** | Nearest-neighbour stop ordering + feasibility verification (time, capacity, distance). Drop and re-sequence if constraints violated. | Turns an abstract schedule into a drivable stop sequence. Transparent: "go to the closest unvisited stop." |
| **Post-processing** | Standby ranking, area-readiness score, review flags (9 active codes), exclusion report (11 reason codes). | Owner sees a one-page summary of any problems before approving the plan. |
| **Config file** | Single `config.json` with T_max, P, R, r, seasonal weight profiles, workload-review thresholds. Schema-validated on load. | Tunable without code changes; version-controlled for reproducibility. |
| **Output artefacts** | Per-route JSON, flags JSON, exclusions JSON, simple text summary, PNG route maps (one per route/day via `mapping.py`). | Machine-readable for Make/Zapier automation; human-readable for the owner. Route maps give instant visual sanity-check. |
| **Map rendering** | Per-route PNG maps using OSMnx road-network graphs, Matplotlib rendering. Road-following paths, colored route segments, depot and stop markers. Implemented in `nes_dispatch/mapping.py`. | Visual review artefact; lets the owner confirm geographic sanity at a glance. |
| **Integration test** | One end-to-end test on example CSVs: validation → Phase 1 → Phase 2 → outputs. Golden-file comparison for deterministic runs. | Proves the pipeline works before it touches real data. |

### What is OUT of Version 1

| Deferred feature | Reason |
|---|---|
| **Iterative Phase 1 ↔ Phase 2 feedback** | Desirable (closes the feasibility gap), but doubles pipeline complexity. Version 1 uses a conservative 80 % T_max buffer instead. |
| **2-opt route improvement** | Worth adding once nearest-neighbour routes are proven adequate. Low complexity, high payoff — good first Version 2 enhancement. |
| **TSP/VRP solver** | Not needed until route quality becomes a measurable problem. Drop-in replacement for the NN step if the need arises. |
| **MILP scheduling** | If the greedy scheduler proves too limited, Phase 1 can be reformulated as a mixed-integer program. The named rules become solver constraints; additive, not a rewrite. |
| **Appointment-time optimisation** | Requires customer preference data not currently in ServiceM8. |
| **Real-time traffic integration** | Google Maps API cost + latency. Static OSMnx/Haversine distances are adequate for weekly planning. |
| **Multi-week rolling horizon** | Needs historical job-outcome data for meaningful look-ahead. |

### Version 1 success criteria

1. The pipeline runs end-to-end on real weekly data without crashing.
2. Every assigned job passes all 10 eligibility rules (post-phase assertions).
3. No route exceeds T_max including travel time.
4. Helper-needed jobs have exactly one primary and one distinct helper technician.
5. The owner can review route proposals + flags + exclusions and approve or reject before anything is booked.
6. A re-run with identical inputs + config produces identical outputs (fully deterministic).

---

## 2  Biggest Pitfall to Avoid

**Skipping the rules layer and jumping straight to route optimisation.**

This is the single highest-risk mistake because:

- **Phase 1 output defines Phase 2 input.** If the scheduling assignment is wrong
  (infeasible triples, over-committed days, eligibility violations), no amount of
  clever routing will fix it — every route will be broken or sub-optimal.

- **Phase 1 is where the owner's policy levers live.** T_max, seasonal weights,
  exceptions, prohibited pairings — all feed into the eligibility check and scoring
  formula. If these are not wired correctly, the engine produces plans the owner
  will consistently override, destroying trust in the tool.

- **Phase 2 is a well-understood problem.** Nearest-neighbour is a reliable
  placeholder; 2-opt or OR-Tools can upgrade it later. The reverse is not true —
  there is no off-the-shelf "weekly service scheduling" that encodes NES-specific
  eligibility, vehicle/tech pairing, area rules, and seasonal weighting.

**Concrete recommendation:** get Phase 1 producing correct, policy-compliant
schedule assignments on real data — verified by the owner — before investing
in route-quality improvements. Nearest-neighbour is sufficient for V1.

### Secondary pitfalls (worth watching)

| Pitfall | Mitigation |
|---|---|
| **Trusting geocodes blindly** | The GEOCODE_OOB validation check must be active from day one. A single wrong coordinate puts a job in the wrong cluster and corrupts the entire route. |
| **Over-tuning parameters before data is stable** | Lock scoring weights and thresholds at documented defaults. Tune only after 4+ weeks of real runs with owner feedback. |
| **Skipping the exclusion report** | The exclusion report is the owner's trust mechanism. If a job is dropped with no explanation, the owner assumes the engine is broken. Always emit a reason code. |
| **Making Airtable schema changes without versioning** | Any field rename or table restructure silently breaks `loaders.py`. Pin expected column names in a schema constant; fail fast on mismatch. |

---

## 3  What Must Be Clarified Before Build

These are open questions that **block or materially change** the implementation.
They should be answered by the project owner / domain expert before writing production code.

### 3.1  Data & integrations

| # | Question | Impact if unanswered |
|---|---|---|
| 1 | **What is the exact Airtable schema?** Table names, field names, field types for: jobs, technicians, vehicles, exceptions, prohibited pairings, area definitions. | `loaders.py` cannot be written. Every column name is a contract. |
| 2 | **How are jobs synced from ServiceM8 → Airtable?** Push or pull? Frequency? Is there a stable `job_id` that survives re-sync? | Risk of duplicate or stale jobs entering the candidate pool. |
| 3 | **What coordinate system does ServiceM8 use?** WGS-84 assumed, but confirm. Any known geocoding failures? | Bounding-box validation thresholds depend on the answer. |
| 4 | **Are vehicle speed and cost-per-km values available today?** The model uses per-vehicle v_k and c_k but current example data uses placeholders. | If not available, use fleet-wide defaults and document the assumption. |

### 3.2  Business rules

| # | Question | Impact if unanswered |
|---|---|---|
| 5 | **What is the real T_max (daily time budget)?** Is it 8 hours wall-clock? Does it include lunch break, morning briefing, end-of-day paperwork? | Directly sets the binding constraint of both phases. |
| 6 | **How are "seasonal" vs "fairness" periods defined?** Exact date ranges, or a formula (e.g. week number)? Who decides to switch? | Determines which weight profile the engine selects. A wrong switch date distorts the entire scoring function. |
| 7 | **Are there hard prohibited pairings today?** If yes, provide the list. If no, confirm the column can be left empty for now. | Eligibility rule `NOT_PROHIBITED` changes shape. |
| 8 | **What qualifies a job as "helper-needed"?** Is it a ServiceM8 field, an Airtable flag, or the owner's manual tag? | Determines the data contract for the helper-assignment pass. |
| 9 | **Is the owner willing to review JSON output, or is a formatted PDF / email required from day one?** | Scopes the output layer — JSON-only is simpler; formatted reports add work. |

### 3.3  Operational

| # | Question | Impact if unanswered |
|---|---|---|
| 10 | **Where does the engine run?** Owner's laptop? A cloud VM? A Make/Zapier webhook trigger? | Determines packaging (pip install vs Docker) and how config/secrets are managed. |
| 11 | **What is the expected weekly cadence?** Run once on Sunday evening? Multiple trial runs with tweaks? | Affects whether we need a CLI with `--dry-run`, an idempotency guard, or a simple one-shot script. |
| 12 | **Who installs and updates the engine?** The owner? A developer? Automatic CI/CD? | Determines documentation depth, error-message clarity, and whether we need a GUI config editor. |

### Priority order

Answer questions **1, 5, 10, 11** first — they determine the data contract, the core
constraint, and the deployment model. Everything else can be refined during
development as long as reasonable defaults are documented.

---

*Document generated from the rules-driven dispatch specification in `main.tex`
and the implementation sketch in `technical_sketch.md`.*
