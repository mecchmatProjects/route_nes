"""CSV loaders — read flat files into domain dataclasses.

Only this module (and output.py) touches the filesystem.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .models import Job, Technician, Vehicle, WeeklyException, WeeklyData


# ── Expected column sets (used by validators too) ───────────────────────────

JOBS_COLUMNS = {
    "job_id", "address", "latitude", "longitude", "area_id", "route_type",
    "helper_needed", "age_days", "value", "service_time_min", "status",
}
TECHNICIANS_COLUMNS = {
    "tech_id", "name", "skills", "home_lat", "home_lon", "available_days",
}
VEHICLES_COLUMNS = {
    "vehicle_id", "vehicle_type", "capability_tags", "available_days",
    "speed_mpm", "cost_per_metre", "capacity",
}
EXCEPTIONS_COLUMNS = {
    "exception_id", "scope_type", "scope_id", "day", "effect_type",
    "effect_value",
}


def _parse_comma_list(raw: str) -> list[str]:
    """Split a comma-separated string into a trimmed list."""
    return [s.strip() for s in raw.split(",") if s.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file and return a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


# ── Per-entity loaders ──────────────────────────────────────────────────────


def load_jobs(rows: list[dict[str, str]]) -> list[Job]:
    jobs: list[Job] = []
    for r in rows:
        jobs.append(Job(
            job_id=r["job_id"].strip(),
            address=r["address"].strip(),
            latitude=float(r["latitude"]),
            longitude=float(r["longitude"]),
            area_id=r["area_id"].strip(),
            route_type=r["route_type"].strip(),
            helper_needed=r["helper_needed"].strip() not in ("0", "false", "False", ""),
            age_days=int(r["age_days"]),
            value=float(r["value"]),
            service_time_min=float(r["service_time_min"]),
            status=r["status"].strip(),
            description=r.get("description", "").strip(),
        ))
    return jobs


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
            speed_mpm=float(r["speed_mpm"]),
            cost_per_metre=float(r["cost_per_metre"]),
            capacity=int(r["capacity"]),
        ))
    return vehicles


def load_exceptions(rows: list[dict[str, str]]) -> list[WeeklyException]:
    exceptions: list[WeeklyException] = []
    for r in rows:
        exceptions.append(WeeklyException(
            exception_id=r["exception_id"].strip(),
            scope_type=r["scope_type"].strip(),
            scope_id=r["scope_id"].strip(),
            day=r["day"].strip(),
            effect_type=r["effect_type"].strip(),
            effect_value=r["effect_value"].strip(),
        ))
    return exceptions


# ── Top-level loader ────────────────────────────────────────────────────────


def load_weekly_data(data_dir: str | Path) -> WeeklyData:
    """Load all four CSVs from *data_dir* and return a WeeklyData container.

    Expected files inside *data_dir*:
        example_jobs.csv, example_technicians.csv,
        example_vehicles.csv, example_weekly_exceptions.csv
    """
    d = Path(data_dir)

    jobs_rows = _read_csv(d / "example_jobs.csv")
    techs_rows = _read_csv(d / "example_technicians.csv")
    vehs_rows = _read_csv(d / "example_vehicles.csv")
    exc_rows = _read_csv(d / "example_weekly_exceptions.csv")

    return WeeklyData(
        jobs=load_jobs(jobs_rows),
        technicians=load_technicians(techs_rows),
        vehicles=load_vehicles(vehs_rows),
        exceptions=load_exceptions(exc_rows),
    )
