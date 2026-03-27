"""Area readiness computation (Technical Sketch §7, Stage 7).

Classifies each area as Good / Moderate / Lean based on scheduled vs
total candidate jobs and standby availability.

* **Good**     – ≥70% of area candidates assigned *and* average standby
                  ≥ weak_standby_threshold.
* **Moderate** – ≥40% assigned *or* average standby ≥ threshold.
* **Lean**     – everything else.
"""

from __future__ import annotations

from typing import Any

from ..data.models import Job, RouteResult


def compute_area_readiness(
    routes: list[RouteResult],
    standby: dict[tuple[str, str, str], list[str]],
    candidate_jobs: list[Job],
    config: dict[str, Any],
) -> dict[str, str]:
    """Return {area_id: "Good" | "Moderate" | "Lean"} for each area."""

    threshold = config.get("weak_standby_threshold", 2)

    # All visited job ids across routes
    all_visited: set[str] = set()
    for r in routes:
        all_visited.update(r.visited_job_ids)

    jobs_by_area: dict[str, list[Job]] = {}
    for j in candidate_jobs:
        jobs_by_area.setdefault(j.area_id, []).append(j)

    # Average standby count per route
    standby_counts = [len(slist) for slist in standby.values()] if standby else [0]
    avg_standby = sum(standby_counts) / max(len(standby_counts), 1)

    result: dict[str, str] = {}

    for area_id, area_jobs in jobs_by_area.items():
        total = len(area_jobs)
        assigned = sum(1 for j in area_jobs if j.job_id in all_visited)
        ratio = assigned / total if total else 0.0

        if ratio >= 0.70 and avg_standby >= threshold:
            result[area_id] = "Good"
        elif ratio >= 0.40 or avg_standby >= threshold:
            result[area_id] = "Moderate"
        else:
            result[area_id] = "Lean"

    return result
