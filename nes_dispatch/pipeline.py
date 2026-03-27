"""Pipeline orchestrator — top-level weekly-run flow.

Implements the step-by-step pipeline from Technical Sketch §6.
Each public function is a pure stage: f(inputs, config) → outputs.
"""

from __future__ import annotations

from .data.models import (
    Exclusion,
    Job,
    Technician,
    Vehicle,
    WeeklyException,
)


# ── Stage 2: Exclusion Filters ──────────────────────────────────────────────


def apply_exclusion_filters(
    jobs: list[Job],
) -> tuple[list[Job], list[Exclusion]]:
    """Partition jobs into candidates and exclusions based on status.

    Returns (candidates, exclusions).
    """
    candidates: list[Job] = []
    exclusions: list[Exclusion] = []

    for j in jobs:
        if j.status == "assigned":
            exclusions.append(Exclusion(
                job_id=j.job_id,
                reason_code="ALREADY_ASSIGNED",
                detail=f"Job status is '{j.status}'",
            ))
        elif j.status in {"excluded", "cancelled"}:
            exclusions.append(Exclusion(
                job_id=j.job_id,
                reason_code="STATUS_EXCLUDED",
                detail=f"Job status is '{j.status}'",
            ))
        else:
            candidates.append(j)

    return candidates, exclusions


# ── Stage 3: Apply Weekly Exceptions ────────────────────────────────────────


def apply_exceptions(
    technicians: list[Technician],
    vehicles: list[Vehicle],
    exceptions: list[WeeklyException],
) -> None:
    """Mutate technician/vehicle available_days in-place based on exceptions.

    • ``unavailable`` → remove the day entirely.
    • ``partial`` → day stays in the list (capacity handled downstream);
      the effect_value is preserved on the exception for later consumption.
    """
    tech_lookup = {t.tech_id: t for t in technicians}
    veh_lookup = {v.vehicle_id: v for v in vehicles}

    for ex in exceptions:
        if ex.scope_type == "technician":
            tech = tech_lookup.get(ex.scope_id)
            if tech is None:
                continue
            if ex.effect_type == "unavailable":
                tech.available_days = [
                    d for d in tech.available_days if d != ex.day
                ]
            # "partial" — keep the day; downstream stages read the exception
            # to reduce capacity / time budget for that (tech, day).

        elif ex.scope_type == "vehicle":
            veh = veh_lookup.get(ex.scope_id)
            if veh is None:
                continue
            if ex.effect_type == "unavailable":
                veh.available_days = [
                    d for d in veh.available_days if d != ex.day
                ]
