"""CSV loaders — read flat files into domain dataclasses.

Aligned with the NES Python Scheduling Engine Build Spec v7 four-payload
input contract.  Only this module (and output.py) touches the filesystem.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from .models import (
    Job, Technician, Vehicle, WeeklyException, WeeklyContext, AreaRule, WeeklyData,
    Exclusion,
)


# ── Expected column sets (used by validators too) ───────────────────────────

JOBS_COLUMNS = {
    "job_id", "address", "city", "state", "area_id", "area_name",
    "job_category", "queue", "latitude", "longitude", "created_date",
    "age_days",
}
JOBS_OPTIONAL_COLUMNS = {
    "required_job_hours", "radiator_count", "refinisher_location",
    "avg_wait_2x_flag", "rebook_count_with_notes", "rebook_count_without_notes",
    "scheduling_preference", "total_job_amount", "description",
}

TECHNICIANS_COLUMNS = {
    "tech_id", "name", "skills", "home_lat", "home_lon", "available_days",
}
VEHICLES_COLUMNS = {
    "vehicle_id", "vehicle_type", "capability_tags", "available_days",
}
VEHICLES_OPTIONAL_COLUMNS = {
    "speed_mpm", "cost_per_metre", "capacity",
}

CONTEXT_COLUMNS = {
    "week_of", "season", "include_v4",
}

EXCEPTIONS_COLUMNS = {
    "exception_id", "week_of", "tech_or_slot", "exception_type", "affected_day",
}

AREA_RULES_COLUMNS = {
    "lookup_item", "lookup_type", "rule_value", "active",
}


def _parse_comma_list(raw: str) -> list[str]:
    """Split a comma-separated string into a trimmed list."""
    return [s.strip() for s in raw.split(",") if s.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file and return a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def _parse_bool(raw: str) -> bool:
    return raw.strip().upper() in ("1", "TRUE", "YES")


def _parse_opt_float(raw: str) -> Optional[float]:
    raw = raw.strip()
    if not raw:
        return None
    return float(raw)


def _parse_opt_int(raw: str) -> Optional[int]:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


# ── Per-entity loaders ──────────────────────────────────────────────────────


def load_jobs(rows: list[dict[str, str]], skip_missing_geocode: bool = True) -> tuple[list[Job], list[Exclusion]]:
    """Load Job records.  If *skip_missing_geocode* is True (default) and
    a row has blank/unparseable lat/lon, the job is skipped and an
    Exclusion record is created (spec §14.2: skip and continue the run).

    Returns (jobs, exclusions).
    """
    jobs: list[Job] = []
    exclusions: list[Exclusion] = []
    for r in rows:
        job_id = r.get("job_id", "").strip()
        # Graceful geocode handling (spec §14.2)
        lat_raw = r.get("latitude", "").strip()
        lon_raw = r.get("longitude", "").strip()
        if not lat_raw or not lon_raw:
            if skip_missing_geocode:
                exclusions.append(Exclusion(
                    job_id=job_id,
                    reason_code="MISSING_GEOCODE",
                    detail=f"Job {job_id} has missing coordinates; skipped.",
                ))
                continue
            lat_raw = lat_raw or "0.0"
            lon_raw = lon_raw or "0.0"
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            if skip_missing_geocode:
                exclusions.append(Exclusion(
                    job_id=job_id,
                    reason_code="MISSING_GEOCODE",
                    detail=f"Job {job_id} has unparseable coordinates; skipped.",
                ))
                continue
            lat, lon = 0.0, 0.0

        jobs.append(Job(
            job_id=r["job_id"].strip(),
            address=r["address"].strip(),
            city=r["city"].strip(),
            state=r["state"].strip(),
            area_id=r["area_id"].strip(),
            area_name=r["area_name"].strip(),
            job_category=r["job_category"].strip(),
            queue=r["queue"].strip(),
            latitude=lat,
            longitude=lon,
            created_date=r.get("created_date", "").strip(),
            age_days=int(r["age_days"]),
            required_job_hours=_parse_opt_float(r.get("required_job_hours", "")),
            radiator_count=_parse_opt_int(r.get("radiator_count", "")),
            refinisher_location=r.get("refinisher_location", "").strip(),
            avg_wait_2x_flag=_parse_bool(r.get("avg_wait_2x_flag", "0")),
            rebook_count_with_notes=int(r.get("rebook_count_with_notes", "0") or 0),
            rebook_count_without_notes=int(r.get("rebook_count_without_notes", "0") or 0),
            scheduling_preference=r.get("scheduling_preference", "").strip(),
            total_job_amount=_parse_opt_float(r.get("total_job_amount", "")),
            description=r.get("description", "").strip(),
        ))
    return jobs, exclusions


def load_technicians(rows: list[dict[str, str]]) -> list[Technician]:
    techs: list[Technician] = []
    for r in rows:
        techs.append(Technician(
            tech_id=r["tech_id"].strip(),
            name=r["name"].strip(),
            skills=_parse_comma_list(r["skills"]),
            home_lat=float(r["home_lat"]),
            home_lon=float(r["home_lon"]),
            available_days=_parse_comma_list(r["available_days"]),
        ))
    return techs


def load_vehicles(rows: list[dict[str, str]]) -> list[Vehicle]:
    vehicles: list[Vehicle] = []
    for r in rows:
        vehicles.append(Vehicle(
            vehicle_id=r["vehicle_id"].strip(),
            vehicle_type=r["vehicle_type"].strip(),
            capability_tags=_parse_comma_list(r["capability_tags"]),
            available_days=_parse_comma_list(r["available_days"]),
            speed_mpm=float(r.get("speed_mpm", "500")),
            cost_per_metre=float(r.get("cost_per_metre", "0.0003")),
            capacity=int(r.get("capacity", "14")),
        ))
    return vehicles


def load_context(rows: list[dict[str, str]]) -> WeeklyContext:
    """Load Weekly Context — expects exactly one row."""
    r = rows[0]
    return WeeklyContext(
        week_of=r["week_of"].strip(),
        season=r["season"].strip(),
        include_v4=_parse_bool(r["include_v4"]),
        helpers_available=int(r.get("helpers_available", "2") or 2),
        holiday_list=r.get("holiday_list", "").strip(),
    )


def load_exceptions(rows: list[dict[str, str]]) -> list[WeeklyException]:
    exceptions: list[WeeklyException] = []
    for r in rows:
        exceptions.append(WeeklyException(
            exception_id=r["exception_id"].strip(),
            week_of=r["week_of"].strip(),
            tech_or_slot=r["tech_or_slot"].strip(),
            exception_type=r["exception_type"].strip(),
            affected_day=r["affected_day"].strip(),
            notes=r.get("notes", "").strip(),
        ))
    return exceptions


def load_area_rules(rows: list[dict[str, str]]) -> list[AreaRule]:
    rules: list[AreaRule] = []
    for r in rows:
        rules.append(AreaRule(
            lookup_item=r["lookup_item"].strip(),
            lookup_type=r["lookup_type"].strip(),
            rule_value=r["rule_value"].strip(),
            active=_parse_bool(r.get("active", "1")),
        ))
    return rules


# ── Top-level loader ────────────────────────────────────────────────────────


def load_weekly_data(data_dir: str | Path) -> WeeklyData:
    """Load all CSVs from *data_dir* and return a WeeklyData container.

    Expected files inside *data_dir*:
        example_jobs.csv          — Candidate Jobs
        example_technicians.csv   — Technician / route-slot lookup
        example_vehicles.csv      — Vehicle lookup
        example_weekly_context.csv — Weekly Context (one row)
        example_weekly_exceptions.csv — Weekly Exceptions
        example_area_rules.csv    — Lookup / Rules Data
    """
    d = Path(data_dir)

    jobs_rows = _read_csv(d / "example_jobs.csv")
    techs_rows = _read_csv(d / "example_technicians.csv")
    vehs_rows = _read_csv(d / "example_vehicles.csv")
    exc_rows = _read_csv(d / "example_weekly_exceptions.csv")

    context: WeeklyContext | None = None
    ctx_path = d / "example_weekly_context.csv"
    if ctx_path.exists():
        ctx_rows = _read_csv(ctx_path)
        if ctx_rows:
            context = load_context(ctx_rows)

    area_rules: list[AreaRule] = []
    rules_path = d / "example_area_rules.csv"
    if rules_path.exists():
        area_rules = load_area_rules(_read_csv(rules_path))

    jobs, load_exclusions = load_jobs(jobs_rows)

    return WeeklyData(
        jobs=jobs,
        technicians=load_technicians(techs_rows),
        vehicles=load_vehicles(vehs_rows),
        exceptions=load_exceptions(exc_rows),
        context=context,
        area_rules=area_rules,
        load_exclusions=load_exclusions,
    )
