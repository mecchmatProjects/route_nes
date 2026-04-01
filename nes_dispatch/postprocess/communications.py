"""Generate Pre-Route and Route Communication records from pipeline outputs.

Spec addendum §4: one Airtable row per issue, not aggregated summary blobs.
"""

from __future__ import annotations

from typing import Any

from ..data.models import (
    Exclusion,
    PreRouteCommunication,
    ReviewFlag,
    RouteCommunication,
    RouteResult,
)

# ── Communication Type mapping ──────────────────────────────────────────────
# Internal code → Airtable-facing Communication Type string.

_EXCLUSION_COMM_TYPES: dict[str, str] = {
    "QUEUE_URGENT": "Queue Exclusion",
    "QUEUE_ON_HOLD": "Queue Exclusion",
    "MISSING_GEOCODE": "Skipped Job",
    "INVALID_CATEGORY": "Skipped Job",
    "NO_ELIGIBLE_TRIPLE": "Capacity Shortfall",
    "SKILL_MISMATCH": "Capacity Shortfall",
    "VEHICLE_MISMATCH": "Capacity Shortfall",
    "V4_CATEGORY_BLOCKED": "Vehicle Restriction",
    "BOOKED_CAP_FULL": "Capacity Shortfall",
    "PROHIBITED_PAIR": "Scheduling Conflict",
    "CAPACITY_FULL": "Capacity Shortfall",
    "TIME_BUDGET": "Capacity Shortfall",
    "CLUSTER_RADIUS": "Geography Issue",
    "ROUTE_DROP": "Route Drop",
}

_SEVERITY_MAP: dict[str, str] = {
    # Exclusion reason codes → communication severity
    "QUEUE_URGENT": "Info",
    "QUEUE_ON_HOLD": "Info",
    "MISSING_GEOCODE": "Action Needed",
    "INVALID_CATEGORY": "Action Needed",
    "NO_ELIGIBLE_TRIPLE": "Warning",
    "SKILL_MISMATCH": "Warning",
    "VEHICLE_MISMATCH": "Warning",
    "V4_CATEGORY_BLOCKED": "Warning",
    "BOOKED_CAP_FULL": "Warning",
    "PROHIBITED_PAIR": "Warning",
    "CAPACITY_FULL": "Warning",
    "TIME_BUDGET": "Warning",
    "CLUSTER_RADIUS": "Warning",
    "ROUTE_DROP": "Warning",
}

# ReviewFlag severity → communication severity
_FLAG_SEVERITY_MAP: dict[str, str] = {
    "INFO": "Info",
    "WARN": "Warning",
    "CRITICAL": "Action Needed",
}

# ReviewFlag code → communication routing (pre_route vs route)
_FLAG_IS_ROUTE_LEVEL: set[str] = {
    "ROUTE_DROP",
    "CROSS_AREA",
    "NO_FEASIBLE",
    "HELPER_REQUIRED",
}

# Flags that indicate weak-but-workable outcomes → outside_normal_parameters=True
_OUTSIDE_NORMAL: set[str] = {
    "NO_FEASIBLE",
    "CROSS_AREA",
}

# Flags that go to Pre-Route by default but ALSO produce a Route Communication
# when they carry route context (spec §8.1: "through Pre-Route OR Route as needed").
_FLAG_ALSO_ROUTE_WHEN_CONTEXT: set[str] = {
    "DUP_ADDR",
}

_FLAG_COMM_TYPES: dict[str, str] = {
    "DUP_ADDR": "Duplicate Review",
    "GEOCODE_OOB": "Skipped Job",
    "WEAK_STANDBY": "Weak Route",
    "HELPER_REQUIRED": "Helper Note",
    "MISSING_PLANNED_HOURS": "Missing Planned Hours",
    "ROUTE_DROP": "Route Drop",
    "CROSS_AREA": "Geography Issue",
    "NO_FEASIBLE": "Weak Route",
    "TECH_OVERLOAD": "Capacity Shortfall",
    "VEH_BOTTLENECK": "Capacity Shortfall",
}


# ── AI Suggested Action for actionable exclusion types (spec Table 8) ────
_AI_SUGGESTED_ACTIONS: dict[str, str] = {
    "MISSING_GEOCODE": "Correct the address and rerun the weekly analysis.",
    "INVALID_CATEGORY": "Verify the job category in ServiceM8 and rerun.",
}


def _next_id(counter: list[int]) -> str:
    """Generate sequential communication IDs."""
    counter[0] += 1
    return f"COM-{counter[0]:05d}"


def generate_pre_route_comms(
    exclusions: list[Exclusion],
    flags: list[ReviewFlag],
    week_of: str,
    run_id: str = "",
) -> list[PreRouteCommunication]:
    """Convert Exclusions and week-level ReviewFlags into Pre-Route records."""
    counter = [0]
    comms: list[PreRouteCommunication] = []

    for ex in exclusions:
        comm_type = _EXCLUSION_COMM_TYPES.get(ex.reason_code, "Skipped Job")
        severity = _SEVERITY_MAP.get(ex.reason_code, "Warning")
        suggested = _AI_SUGGESTED_ACTIONS.get(ex.reason_code, "")

        comms.append(PreRouteCommunication(
            communication_id=_next_id(counter),
            communication_type=comm_type,
            severity=severity,
            schedule_week=week_of,
            message=f"Job {ex.job_id}: {ex.detail}",
            created_by_run=run_id,
            job_number=ex.job_id,
            what_needs_fixing=ex.detail,
            ai_suggested_action=suggested,
        ))

    for flag in flags:
        if flag.code in _FLAG_IS_ROUTE_LEVEL:
            continue  # handled by generate_route_comms
        comm_type = _FLAG_COMM_TYPES.get(flag.code, "Review Note")
        severity = _FLAG_SEVERITY_MAP.get(flag.severity, "Info")
        job_id = flag.refs.get("job_id", "")
        route_day = flag.refs.get("day", "")
        route_slot = flag.refs.get("tech_id", "")

        comms.append(PreRouteCommunication(
            communication_id=_next_id(counter),
            communication_type=comm_type,
            severity=severity,
            schedule_week=week_of,
            message=flag.message,
            created_by_run=run_id,
            job_number=job_id,
            route_day=route_day,
            route_slot=route_slot,
        ))

    return comms


def generate_route_comms(
    flags: list[ReviewFlag],
    routes: list[RouteResult],
    week_of: str,
    run_id: str = "",
) -> list[RouteCommunication]:
    """Convert route-level ReviewFlags into Route Communication records."""
    counter = [0]
    comms: list[RouteCommunication] = []

    # Build a lookup: job_id → (tech_id, day)
    job_route: dict[str, tuple[str, str]] = {}
    for r in routes:
        for jid in r.visited_job_ids:
            job_route[jid] = (r.tech_id, r.day)

    for flag in flags:
        # Exclusively route-level flags
        is_route = flag.code in _FLAG_IS_ROUTE_LEVEL
        # Flags that are also routed to Route when they carry route context
        # (spec §8.1: "Pre-Route OR Route Communications as needed")
        is_also_route = (
            flag.code in _FLAG_ALSO_ROUTE_WHEN_CONTEXT
            and ("day" in flag.refs or "tech_id" in flag.refs)
        )
        if not is_route and not is_also_route:
            continue

        comm_type = _FLAG_COMM_TYPES.get(flag.code, "Route Note")
        severity = _FLAG_SEVERITY_MAP.get(flag.severity, "Info")

        route_day = flag.refs.get("day", "")
        route_slot = flag.refs.get("tech_id", "")
        job_id = flag.refs.get("job_id", "")

        # Attempt to resolve from job_route if missing
        if not route_day and job_id in job_route:
            route_slot, route_day = job_route[job_id]

        comms.append(RouteCommunication(
            communication_id=_next_id(counter),
            communication_type=comm_type,
            severity=severity,
            schedule_week=week_of,
            message=flag.message,
            route_day=route_day,
            route_slot=route_slot,
            created_by_run=run_id,
            job_number=job_id,
            # affected_window: populated once booking-window logic is implemented (deferred)
            outside_normal_parameters=(flag.code in _OUTSIDE_NORMAL),
        ))

    return comms
