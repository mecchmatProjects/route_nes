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
| **Layer 1 — Scheduling MILP** | Pyomo model with constraints S1–S8, objective (weighted job value + λ·uniformity). Greedy fallback if solver is unavailable. | Core value: decide *which* jobs happen on *which* day, with *whom* and *what vehicle*. |
| **Layer 2 — Routing** | Cluster construction (Algorithm 1) → intra-cluster MILP (MTZ subtour elimination) or SA solver. | Turns an abstract schedule into a drivable stop sequence. |
| **Post-processing** | Standby ranking, area-readiness score, review flags (10 codes), exclusion report (11 reason codes). | Owner sees a one-page summary of any problems before approving the plan. |
| **Config file** | Single `config.json` with λ, T_max, P, R, r, seasonal profiles, SA hyper-params, solver timeout, random seed. Schema-validated on load. | Tunable without code changes; version-controlled for reproducibility. |
| **Output artefacts** | Per-route JSON, flags JSON, exclusions JSON, simple text summary. | Machine-readable for Make/Zapier automation; human-readable for the owner. |
| **Integration test** | One end-to-end test on example CSVs: validation → L1 → L2 → outputs. Golden-file comparison for deterministic runs. | Proves the pipeline works before it touches real data. |

### What is OUT of Version 1

| Deferred feature | Reason |
|---|---|
| **Helper-job modelling (S9–S11, y^H)** | Two-man jobs add a second assignment variable per job-day. The maths is defined in `main.tex` and ready to implement, but real helper data (who can pair with whom, separate travel time) needs to be collected and validated first. Ship without it; add once data exists. |
| **Iterative L1 ↔ L2 feedback** | Desirable (closes the feasibility gap), but doubles pipeline complexity. Version 1 uses a conservative 80 % T_max buffer instead. |
| **Appointment-time optimisation** | Requires customer preference data not currently in ServiceM8. |
| **Real-time traffic integration** | Google Maps API cost + latency. Static OSMnx distances are adequate for weekly planning. |
| **Multi-week rolling horizon** | Needs historical job-outcome data for meaningful look-ahead. |
| **Map rendering** | Nice to have; the text / JSON output is sufficient for the owner to review routes. Can be added as a thin `output.py` extension later. |

### Version 1 success criteria

1. The pipeline runs end-to-end on real weekly data without crashing.
2. Every assigned job is eligible (passes all S1–S8 post-layer assertions).
3. No route exceeds T_max including travel time.
4. The owner can review route proposals + flags + exclusions and approve or reject before anything is booked.
5. A re-run with identical inputs + config + seed produces identical outputs.

---

## 2  Biggest Pitfall to Avoid

**Building the routing layer (Layer 2) before the scheduling layer (Layer 1) is solid.**

This is the single highest-risk mistake because:

- **Layer 1 output defines Layer 2 input.** If the scheduling assignment is wrong
  (infeasible triples, over-committed days, eligibility violations), no amount of
  clever routing will fix it — every route will be broken or sub-optimal.

- **Layer 1 is where the owner's policy levers live.** λ, T_max, seasonal weights,
  exceptions — all feed into the MILP objective and constraints. If these are
  not wired correctly, the engine produces plans the owner will consistently
  override, destroying trust in the tool.

- **Layer 2 is a well-understood VRP.** Off-the-shelf TSP/VRP heuristics (SA, OR-Tools,
  even Google Maps reordering) can fill in temporarily while Layer 1 stabilises.
  The reverse is not true — there is no off-the-shelf "weekly service scheduling"
  that encodes NES-specific eligibility, vehicle/tech pairing, area rules, and
  seasonal weighting.

**Concrete recommendation:** get Layer 1 producing correct, policy-compliant
schedule assignments on real data — verified by the owner — before writing a
single line of Layer 2 MILP code. Use a trivial nearest-neighbour route ordering
as a placeholder for Layer 2 during this phase.

### Secondary pitfalls (worth watching)

| Pitfall | Mitigation |
|---|---|
| **Trusting geocodes blindly** | The GEOCODE_OOB validation check must be active from day one. A single wrong coordinate puts a job in the wrong cluster and corrupts the entire route. |
| **Over-tuning solver parameters before data is stable** | Lock SA hyper-params and λ at documented defaults. Tune only after 4+ weeks of real runs with owner feedback. |
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
| 5 | **What is the real T_max (daily time budget)?** Is it 8 hours wall-clock? Does it include lunch break, morning briefing, end-of-day paperwork? | Directly sets the binding constraint of both layers. |
| 6 | **How are "seasonal" vs "fairness" periods defined?** Exact date ranges, or a formula (e.g. week number)? Who decides to switch? | Determines which weight profile the engine selects. A wrong switch date distorts the entire scoring function. |
| 7 | **Are there hard prohibited pairings today?** If yes, provide the list. If no, confirm the column can be left empty for now. | Constraint S5 (eligibility) changes shape. |
| 8 | **What qualifies a job as "helper-needed"?** Is it a ServiceM8 field, an Airtable flag, or the owner's manual tag? | Determines whether helper logic is in scope for V1 at all. |
| 9 | **Is the owner willing to review JSON output, or is a formatted PDF / email required from day one?** | Scopes the output layer — JSON-only is a week of work; formatted reports add another. |

### 3.3  Operational

| # | Question | Impact if unanswered |
|---|---|---|
| 10 | **Where does the engine run?** Owner's laptop? A cloud VM? A Make/Zapier webhook trigger? | Determines packaging (pip install vs Docker), solver availability (CBC prebuilt or compile), and how config/secrets are managed. |
| 11 | **What is the expected weekly cadence?** Run once on Sunday evening? Multiple trial runs with tweaks? | Affects whether we need a CLI with `--dry-run`, an idempotency guard, or a simple one-shot script. |
| 12 | **Who installs and updates the engine?** The owner? A developer? Automatic CI/CD? | Determines documentation depth, error-message clarity, and whether we need a GUI config editor. |
| 13 | **Is there a budget for a commercial solver (Gurobi, CPLEX)?** CBC is free but slower on large instances. | If yes, the MILP model stays as-is. If no, we may need solver time-limits or decomposition heuristics sooner. |

### Priority order

Answer questions **1, 5, 10, 11** first — they determine the data contract, the core
constraint, and the deployment model. Everything else can be refined during
development as long as reasonable defaults are documented.

---

*Document generated from the two-layer dispatch model described in `main.tex`
and the implementation sketch in `technical_sketch.md`.*
