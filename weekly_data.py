#!/usr/bin/env python3
"""
weekly_data.py — Create, read, and validate weekly planning data files
for the NES dispatch-routing engine.

Aligned with the NES Python Scheduling Engine Build Spec v7 four-payload
input contract: Candidate Jobs, Weekly Context, Weekly Exceptions,
Lookup / Rules Data.

Supports two modes:
  1. Offline / file-based:  read example CSVs from data/ folder.
  2. ServiceM8 live pull:   fetch jobs via ServiceM8 REST API and write CSVs.

Usage:
  # Generate fresh example data
  python weekly_data.py --generate

  # Load existing example files and print summary
  python weekly_data.py --load

  # Pull from ServiceM8 API and write CSVs (requires env vars)
  python weekly_data.py --servicem8
"""

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field, asdict
from math import radians, cos, sin, sqrt, atan2
from pathlib import Path
from typing import List, Optional

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"

FILES = {
    "jobs": DATA_DIR / "example_jobs.csv",
    "technicians": DATA_DIR / "example_technicians.csv",
    "vehicles": DATA_DIR / "example_vehicles.csv",
    "exceptions": DATA_DIR / "example_weekly_exceptions.csv",
    "context": DATA_DIR / "example_weekly_context.csv",
    "area_rules": DATA_DIR / "example_area_rules.csv",
}

SERVICEM8_API = "https://api.servicem8.com/api_1.0"

VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri"}
VALID_FULL_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}

# Job categories per spec addendum Table 7
FIXED_HOUR_CATEGORIES = {
    "Boiler Maintenance": 1.0,
    "Estimate": 1.0,
    "Go Back": 1.0,
    "New Boiler Visit": 1.0,
    "Radiator Pick-Up": 1.0,
    "Radiator Service": 1.0,
    "Service Call": 1.0,
    "Steam System Inspection": 1.0,
}

ELIGIBLE_QUEUES = {"Priority", "Accepted Quotes", "Requested Scheduling", "Normal jobs"}
EXCLUDED_QUEUES = {"Urgent", "On Hold"}


# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """Candidate Jobs payload (spec §14.1 / addendum Table 3)."""
    job_id: str
    address: str
    city: str
    state: str
    area_id: str
    area_name: str
    job_category: str
    queue: str
    latitude: float
    longitude: float
    created_date: str
    age_days: int
    required_job_hours: Optional[float] = None
    radiator_count: Optional[int] = None
    refinisher_location: str = ""
    avg_wait_2x_flag: bool = False
    rebook_count_with_notes: int = 0
    rebook_count_without_notes: int = 0
    scheduling_preference: str = ""
    total_job_amount: Optional[float] = None
    description: str = ""


@dataclass
class Technician:
    tech_id: str
    name: str
    skills: List[str]
    home_lat: float
    home_lon: float
    available_days: List[str]


@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str
    capability_tags: List[str]
    available_days: List[str]
    speed_mpm: float = 500.0
    cost_per_metre: float = 0.0003
    capacity: int = 14


@dataclass
class WeeklyContext:
    """Weekly Context payload (addendum Table 4)."""
    week_of: str
    season: str
    include_v4: bool
    helpers_available: int = 2
    holiday_list: str = ""


@dataclass
class WeeklyException:
    """Weekly Exceptions payload (addendum Table 5)."""
    exception_id: str
    week_of: str
    tech_or_slot: str
    exception_type: str
    affected_day: str
    notes: str = ""


@dataclass
class AreaRule:
    """Lookup / Rules Data payload (addendum Table 6)."""
    lookup_item: str
    lookup_type: str
    rule_value: str
    active: bool = True


@dataclass
class WeeklyData:
    """Container returned by every loader — the planning engine's input."""
    jobs: List[Job] = field(default_factory=list)
    technicians: List[Technician] = field(default_factory=list)
    vehicles: List[Vehicle] = field(default_factory=list)
    exceptions: List[WeeklyException] = field(default_factory=list)
    context: Optional[WeeklyContext] = None
    area_rules: List[AreaRule] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Haversine helper
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two lat/lon points."""
    R = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ---------------------------------------------------------------------------
# CSV readers
# ---------------------------------------------------------------------------

def _parse_list(raw: str) -> List[str]:
    """Split a comma-separated string stored in a single CSV cell."""
    return [s.strip() for s in raw.split(",") if s.strip()]


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


def load_jobs(path: Path) -> List[Job]:
    jobs = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # Graceful geocode handling (spec §14.2)
            lat_raw = row.get("latitude", "").strip()
            lon_raw = row.get("longitude", "").strip()
            if not lat_raw or not lon_raw:
                continue  # skip job; surfaced via communications
            try:
                lat = float(lat_raw)
                lon = float(lon_raw)
            except ValueError:
                continue

            jobs.append(Job(
                job_id=row["job_id"],
                address=row["address"],
                city=row["city"],
                state=row["state"],
                area_id=row["area_id"],
                area_name=row["area_name"],
                job_category=row["job_category"],
                queue=row["queue"],
                latitude=lat,
                longitude=lon,
                created_date=row.get("created_date", ""),
                age_days=int(row["age_days"]),
                required_job_hours=_parse_opt_float(row.get("required_job_hours", "")),
                radiator_count=_parse_opt_int(row.get("radiator_count", "")),
                refinisher_location=row.get("refinisher_location", ""),
                avg_wait_2x_flag=_parse_bool(row.get("avg_wait_2x_flag", "0")),
                rebook_count_with_notes=int(row.get("rebook_count_with_notes", "0") or 0),
                rebook_count_without_notes=int(row.get("rebook_count_without_notes", "0") or 0),
                scheduling_preference=row.get("scheduling_preference", ""),
                total_job_amount=_parse_opt_float(row.get("total_job_amount", "")),
                description=row.get("description", ""),
            ))
    return jobs


def load_technicians(path: Path) -> List[Technician]:
    techs = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            techs.append(Technician(
                tech_id=row["tech_id"],
                name=row["name"],
                skills=_parse_list(row["skills"]),
                home_lat=float(row["home_lat"]),
                home_lon=float(row["home_lon"]),
                available_days=_parse_list(row["available_days"]),
            ))
    return techs


def load_vehicles(path: Path) -> List[Vehicle]:
    vehicles = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vehicles.append(Vehicle(
                vehicle_id=row["vehicle_id"],
                vehicle_type=row["vehicle_type"],
                capability_tags=_parse_list(row["capability_tags"]),
                available_days=_parse_list(row["available_days"]),
                speed_mpm=float(row.get("speed_mpm", 500)),
                cost_per_metre=float(row.get("cost_per_metre", 0.0003)),
                capacity=int(row.get("capacity", 14)),
            ))
    return vehicles


def load_context(path: Path) -> Optional[WeeklyContext]:
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    r = rows[0]
    return WeeklyContext(
        week_of=r["week_of"],
        season=r["season"],
        include_v4=_parse_bool(r["include_v4"]),
        helpers_available=int(r.get("helpers_available", 2) or 2),
        holiday_list=r.get("holiday_list", ""),
    )


def load_exceptions(path: Path) -> List[WeeklyException]:
    exceptions = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            exceptions.append(WeeklyException(
                exception_id=row["exception_id"],
                week_of=row["week_of"],
                tech_or_slot=row["tech_or_slot"],
                exception_type=row["exception_type"],
                affected_day=row["affected_day"],
                notes=row.get("notes", ""),
            ))
    return exceptions


def load_area_rules(path: Path) -> List[AreaRule]:
    if not path.exists():
        return []
    rules = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rules.append(AreaRule(
                lookup_item=row["lookup_item"],
                lookup_type=row["lookup_type"],
                rule_value=row["rule_value"],
                active=_parse_bool(row.get("active", "1")),
            ))
    return rules


def load_weekly_data(data_dir: Optional[Path] = None) -> WeeklyData:
    """Load all CSV files from *data_dir* and return a WeeklyData."""
    d = data_dir or DATA_DIR
    return WeeklyData(
        jobs=load_jobs(d / "example_jobs.csv"),
        technicians=load_technicians(d / "example_technicians.csv"),
        vehicles=load_vehicles(d / "example_vehicles.csv"),
        exceptions=load_exceptions(d / "example_weekly_exceptions.csv"),
        context=load_context(d / "example_weekly_context.csv"),
        area_rules=load_area_rules(d / "example_area_rules.csv"),
    )


# ---------------------------------------------------------------------------
# CSV writers (used by --generate and --servicem8)
# ---------------------------------------------------------------------------

JOB_COLS = [
    "job_id", "address", "city", "state", "area_id", "area_name",
    "job_category", "queue", "latitude", "longitude", "created_date",
    "age_days", "required_job_hours", "radiator_count", "refinisher_location",
    "avg_wait_2x_flag", "rebook_count_with_notes", "rebook_count_without_notes",
    "scheduling_preference", "total_job_amount", "description",
]


def write_jobs(jobs: List[Job], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=JOB_COLS)
        w.writeheader()
        for j in jobs:
            row = asdict(j)
            row["avg_wait_2x_flag"] = str(row["avg_wait_2x_flag"]).upper()
            if row["required_job_hours"] is None:
                row["required_job_hours"] = ""
            if row["radiator_count"] is None:
                row["radiator_count"] = ""
            if row["total_job_amount"] is None:
                row["total_job_amount"] = ""
            w.writerow(row)


def write_technicians(techs: List[Technician], path: Path) -> None:
    cols = ["tech_id", "name", "skills", "home_lat", "home_lon", "available_days"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in techs:
            row = asdict(t)
            row["skills"] = ",".join(row["skills"])
            row["available_days"] = ",".join(row["available_days"])
            w.writerow(row)


def write_vehicles(vehicles: List[Vehicle], path: Path) -> None:
    cols = ["vehicle_id", "vehicle_type", "capability_tags", "available_days",
            "speed_mpm", "cost_per_metre", "capacity"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for v in vehicles:
            row = asdict(v)
            row["capability_tags"] = ",".join(row["capability_tags"])
            row["available_days"] = ",".join(row["available_days"])
            w.writerow(row)


def write_context(ctx: WeeklyContext, path: Path) -> None:
    cols = ["week_of", "season", "include_v4", "helpers_available", "holiday_list"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        row = asdict(ctx)
        row["include_v4"] = str(row["include_v4"]).upper()
        w.writerow(row)


def write_exceptions(exceptions: List[WeeklyException], path: Path) -> None:
    cols = ["exception_id", "week_of", "tech_or_slot", "exception_type",
            "affected_day", "notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for e in exceptions:
            w.writerow(asdict(e))


def write_area_rules(rules: List[AreaRule], path: Path) -> None:
    cols = ["lookup_item", "lookup_type", "rule_value", "active"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rules:
            row = asdict(r)
            row["active"] = str(row["active"]).upper()
            w.writerow(row)


def write_weekly_data(wd: WeeklyData, data_dir: Optional[Path] = None) -> None:
    d = data_dir or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    write_jobs(wd.jobs, d / "example_jobs.csv")
    write_technicians(wd.technicians, d / "example_technicians.csv")
    write_vehicles(wd.vehicles, d / "example_vehicles.csv")
    write_exceptions(wd.exceptions, d / "example_weekly_exceptions.csv")
    if wd.context:
        write_context(wd.context, d / "example_weekly_context.csv")
    if wd.area_rules:
        write_area_rules(wd.area_rules, d / "example_area_rules.csv")
    print(f"Wrote {len(wd.jobs)} jobs, {len(wd.technicians)} techs, "
          f"{len(wd.vehicles)} vehicles, {len(wd.exceptions)} exceptions, "
          f"{'1 context' if wd.context else 'no context'}, "
          f"{len(wd.area_rules)} area rules → {d}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(wd: WeeklyData) -> List[str]:
    """Return a list of warning/error strings. Empty list = valid."""
    issues: List[str] = []

    tech_names = {t.name for t in wd.technicians}
    tech_ids = {t.tech_id for t in wd.technicians}
    valid_refs = tech_names | tech_ids

    for j in wd.jobs:
        if j.queue not in ELIGIBLE_QUEUES and j.queue not in EXCLUDED_QUEUES:
            issues.append(f"{j.job_id}: unknown queue '{j.queue}'")
        if j.age_days < 0:
            issues.append(f"{j.job_id}: negative age {j.age_days}")

    for ex in wd.exceptions:
        if ex.tech_or_slot not in valid_refs:
            issues.append(f"{ex.exception_id}: unknown tech/slot '{ex.tech_or_slot}'")
        if ex.affected_day not in VALID_FULL_DAYS and ex.affected_day not in VALID_DAYS:
            issues.append(f"{ex.exception_id}: invalid day '{ex.affected_day}'")

    # Duplicate-address detection (with 15 Monticello exception)
    addr_groups: dict = {}
    for j in wd.jobs:
        addr_groups.setdefault(j.address, []).append(j)
    for addr, jlist in addr_groups.items():
        if len(jlist) > 1:
            # Spec: multiple radiator replacement slave jobs at 15 Monticello
            # Providence must never be treated as duplicates
            if "15 Monticello" in addr and all(
                "radiator" in j.job_category.lower() or "Radiator" in j.job_category
                for j in jlist
            ):
                continue
            issues.append(
                f"Duplicate address '{addr}': "
                f"{[j.job_id for j in jlist]}"
            )

    return issues


# ---------------------------------------------------------------------------
# ServiceM8 live pull
# ---------------------------------------------------------------------------

def _sm8_headers() -> dict:
    """Build auth headers.  Expects SERVICEM8_TOKEN env var (bearer token)."""
    token = os.getenv("SERVICEM8_TOKEN")
    if not token:
        raise ValueError(
            "Set SERVICEM8_TOKEN env var to a valid bearer token. "
            "See api_credentials_setup.md for instructions."
        )
    return {"Authorization": f"Bearer {token}"}


def _sm8_get(endpoint: str) -> list:
    headers = _sm8_headers()
    resp = requests.get(f"{SERVICEM8_API}/{endpoint}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _map_sm8_category(sm8_job: dict) -> str:
    """Map ServiceM8 job fields to a spec job_category."""
    cat = (sm8_job.get("category") or sm8_job.get("job_category") or "").strip()
    if cat:
        return cat
    desc = (sm8_job.get("description") or "").lower()
    if "radiator" in desc and "refinish" in desc:
        return "Radiator Refinishing"
    if "radiator" in desc and "replace" in desc:
        return "Radiator Replacement"
    if "radiator" in desc:
        return "Radiator Service"
    if "boiler" in desc and "new" in desc:
        return "New Boiler Visit"
    if "boiler" in desc:
        return "Boiler Maintenance"
    if "steam" in desc and "inspection" in desc:
        return "Steam System Inspection"
    if "trap" in desc:
        return "Trap Service"
    if "insulation" in desc:
        return "Insulation"
    if "install" in desc:
        return "New Equipment Installation Other Than Boiler"
    return "Service Call"


def _map_sm8_queue(sm8_job: dict) -> str:
    """Map ServiceM8 status/queue to spec queue names."""
    q = (sm8_job.get("queue") or sm8_job.get("status") or "").strip()
    queue_map = {
        "urgent": "Urgent",
        "on hold": "On Hold",
        "priority": "Priority",
        "accepted quotes": "Accepted Quotes",
        "requested scheduling": "Requested Scheduling",
        "normal": "Normal jobs",
    }
    return queue_map.get(q.lower(), "Normal jobs")


def fetch_servicem8_jobs() -> List[Job]:
    """Pull active jobs from ServiceM8 and convert to Job dataclass list."""
    raw_jobs = _sm8_get("job.json")
    jobs: List[Job] = []
    for idx, rj in enumerate(raw_jobs, start=1):
        status_raw = (rj.get("status") or "").lower()
        if status_raw in ("completed", "cancelled", "deleted"):
            continue

        lat = rj.get("geo_latitude") or rj.get("address_latitude")
        lon = rj.get("geo_longitude") or rj.get("address_longitude")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue

        jobs.append(Job(
            job_id=rj.get("uuid", f"SM8-{idx:04d}"),
            address=rj.get("job_address", ""),
            city=rj.get("city", ""),
            state=rj.get("state", "RI"),
            area_id=rj.get("area_uuid", "00"),
            area_name=rj.get("area_name", ""),
            job_category=_map_sm8_category(rj),
            queue=_map_sm8_queue(rj),
            latitude=lat,
            longitude=lon,
            created_date=rj.get("date", ""),
            age_days=0,  # compute externally from created_date
            required_job_hours=_parse_opt_float(
                str(rj.get("required_job_hours") or rj.get("estimated_duration") or "")
            ),
            radiator_count=_parse_opt_int(str(rj.get("radiator_count") or "")),
            refinisher_location=rj.get("refinisher_location", ""),
            description=rj.get("description", ""),
        ))
    return jobs


def fetch_servicem8_staff() -> List[Technician]:
    """Pull active staff from ServiceM8 and convert to Technician list."""
    raw = _sm8_get("staff.json")
    techs: List[Technician] = []
    for s in raw:
        if (s.get("active") or "1") == "0":
            continue
        techs.append(Technician(
            tech_id=s.get("uuid", ""),
            name=f"{s.get('first', '')} {s.get('last', '')}".strip(),
            skills=["boiler_service"],  # refine from Airtable skill table
            home_lat=0.0,
            home_lon=0.0,
            available_days=list(VALID_DAYS),
        ))
    return techs


def pull_servicem8_weekly(data_dir: Optional[Path] = None) -> WeeklyData:
    """Fetch jobs + staff from ServiceM8, write CSVs, return WeeklyData."""
    print("Fetching jobs from ServiceM8...")
    jobs = fetch_servicem8_jobs()
    print(f"  → {len(jobs)} candidate jobs")

    print("Fetching staff from ServiceM8...")
    techs = fetch_servicem8_staff()
    print(f"  → {len(techs)} active technicians")

    d = data_dir or DATA_DIR
    vehicles: List[Vehicle] = []
    exceptions: List[WeeklyException] = []
    context: Optional[WeeklyContext] = None
    area_rules: List[AreaRule] = []

    veh_path = d / "example_vehicles.csv"
    exc_path = d / "example_weekly_exceptions.csv"
    ctx_path = d / "example_weekly_context.csv"
    rules_path = d / "example_area_rules.csv"

    if veh_path.exists():
        vehicles = load_vehicles(veh_path)
    if exc_path.exists():
        exceptions = load_exceptions(exc_path)
    if ctx_path.exists():
        context = load_context(ctx_path)
    if rules_path.exists():
        area_rules = load_area_rules(rules_path)

    wd = WeeklyData(jobs=jobs, technicians=techs, vehicles=vehicles,
                    exceptions=exceptions, context=context,
                    area_rules=area_rules)
    write_weekly_data(wd, d)
    return wd


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(wd: WeeklyData) -> None:
    print("=" * 60)
    print("WEEKLY PLANNING DATA SUMMARY")
    print("=" * 60)

    if wd.context:
        ctx = wd.context
        print(f"\nWeekly Context: week_of={ctx.week_of}  season={ctx.season}  "
              f"V-4={'ON' if ctx.include_v4 else 'OFF'}  "
              f"helpers={ctx.helpers_available}")
        if ctx.holiday_list:
            print(f"  Holidays: {ctx.holiday_list}")

    print(f"\nJobs: {len(wd.jobs)}")
    by_queue: dict = {}
    by_cat: dict = {}
    for j in wd.jobs:
        by_queue.setdefault(j.queue, []).append(j)
        by_cat.setdefault(j.job_category, []).append(j)
    print("  By queue:")
    for q, jlist in sorted(by_queue.items()):
        print(f"    {q:25s}  {len(jlist):3d} jobs")
    print("  By category:")
    for c, jlist in sorted(by_cat.items()):
        print(f"    {c:45s}  {len(jlist):3d} jobs")

    print(f"\nTechnicians: {len(wd.technicians)}")
    for t in wd.technicians:
        print(f"  {t.tech_id}  {t.name:20s}  days={','.join(t.available_days)}")

    print(f"\nVehicles: {len(wd.vehicles)}")
    for v in wd.vehicles:
        print(f"  {v.vehicle_id}  {v.vehicle_type:18s}  "
              f"cap={v.capacity}  days={','.join(v.available_days)}")

    print(f"\nWeekly Exceptions: {len(wd.exceptions)}")
    for ex in wd.exceptions:
        print(f"  {ex.exception_id}  {ex.tech_or_slot}  "
              f"{ex.affected_day}  {ex.exception_type} ({ex.notes})")

    print(f"\nArea Rules: {len(wd.area_rules)}")
    for rule in wd.area_rules:
        status = "active" if rule.active else "inactive"
        print(f"  [{status}] {rule.lookup_item}: {rule.rule_value[:60]}")

    issues = validate(wd)
    if issues:
        print(f"\nValidation issues ({len(issues)}):")
        for issue in issues:
            print(f"  ⚠ {issue}")
    else:
        print("\n✓ All validation checks passed.")

    # Distance summary from Providence shop to all jobs
    prov_lat, prov_lon = 41.8180, -71.4350  # Providence shop
    if wd.jobs:
        dists = [(j.job_id, haversine(prov_lat, prov_lon,
                                       j.latitude, j.longitude))
                 for j in wd.jobs]
        dists.sort(key=lambda x: x[1])
        print(f"\nDistances from Providence shop:")
        for jid, d in dists[:10]:
            print(f"  {jid}  {d/1000:6.1f} km")
        if len(dists) > 10:
            print(f"  ... and {len(dists)-10} more")


# ---------------------------------------------------------------------------
# Example data generator
# ---------------------------------------------------------------------------

def generate_example_data() -> WeeklyData:
    """Build example data programmatically and write to data/ folder."""
    jobs = [
        Job("SM8-10452", "123 Broadway", "Providence", "RI", "01", "Providence Core",
            "Service Call", "Normal jobs", 41.8240, -71.4128, "2026-03-03", 28,
            description="Annual boiler service"),
        Job("SM8-10510", "456 Hope St", "Providence", "RI", "01", "Providence Core",
            "Boiler Maintenance", "Normal jobs", 41.8365, -71.3985, "2026-03-17", 14,
            description="Routine boiler maintenance"),
        Job("SM8-10588", "789 Elmwood Ave", "Providence", "RI", "02", "Providence South",
            "Steam System Inspection", "Normal jobs", 41.8010, -71.4180, "2026-03-10", 21,
            description="Steam system inspection"),
        Job("SM8-10631", "34 Wickenden St", "Providence", "RI", "01", "Providence Core",
            "Vent / Trap / Repair / Piping Work", "Priority", 41.8195, -71.4005, "2026-01-15", 75,
            required_job_hours=2.5, avg_wait_2x_flag=True,
            description="Vent and trap repair - overdue"),
        Job("SM8-10677", "88 Atwells Ave", "Providence", "RI", "03", "Federal Hill",
            "Service Call", "Normal jobs", 41.8260, -71.4260, "2026-03-20", 11,
            description="Thermostat issue"),
        Job("SM8-10690", "22 Thayer St", "Providence", "RI", "01", "Providence Core",
            "Estimate", "Requested Scheduling", 41.8285, -71.4010, "2026-03-12", 19,
            rebook_count_with_notes=1,
            scheduling_preference="Tuesday or Thursday mornings preferred",
            description="Estimate for new system"),
        Job("SM8-10491", "55 Westminster St", "Providence", "RI", "01", "Providence Core",
            "Go Back", "Normal jobs", 41.8230, -71.4175, "2026-03-24", 7,
            description="Follow-up from prior visit"),
        Job("SM8-20311", "100 Broad St", "Cranston", "RI", "04", "Cranston",
            "Boiler Maintenance", "Normal jobs", 41.7735, -71.4375, "2026-03-05", 26,
            description="Annual boiler maintenance"),
        Job("SM8-20314", "210 Reservoir Ave", "Cranston", "RI", "04", "Cranston",
            "Trap Service", "Normal jobs", 41.7680, -71.4290, "2026-03-14", 17,
            required_job_hours=1.5, description="Trap service - 3 traps"),
        Job("SM8-20319", "45 Phenix Ave", "Cranston", "RI", "04", "Cranston",
            "Service Call", "Accepted Quotes", 41.7620, -71.4400, "2026-02-20", 39,
            required_job_hours=3.0, total_job_amount=1050.0,
            description="Accepted quote for piping work"),
        Job("SM8-20341", "78 Pontiac Ave", "Cranston", "RI", "04", "Cranston",
            "Insulation", "Normal jobs", 41.7700, -71.4330, "2026-03-18", 13,
            required_job_hours=2.0, description="Pipe insulation job"),
        Job("SM8-20356", "300 Park Ave", "Cranston", "RI", "04", "Cranston",
            "New Boiler Visit", "Normal jobs", 41.7750, -71.4350, "2026-03-22", 9,
            description="New boiler visit consultation"),
        Job("SM8-30402", "15 Monticello Rd", "Providence", "RI", "05", "Refinisher",
            "Radiator Replacement", "Normal jobs", 41.8180, -71.4350, "2026-03-08", 23,
            radiator_count=3, refinisher_location="Providence",
            description="Radiator replacement - 3 units"),
        Job("SM8-30405", "15 Monticello Rd", "Providence", "RI", "05", "Refinisher",
            "Radiator Pick-Up", "Normal jobs", 41.8180, -71.4350, "2026-03-15", 16,
            radiator_count=2, refinisher_location="Providence",
            description="Radiator pickup for refinishing"),
        Job("SM8-30411", "67 Valley St", "Providence", "RI", "02", "Providence South",
            "Radiator Refinishing", "Normal jobs", 41.8100, -71.4220, "2026-03-06", 25,
            radiator_count=4, refinisher_location="Providence",
            description="Radiator refinishing - 4 units"),
        Job("SM8-30440", "120 Charles St", "Providence", "RI", "01", "Providence Core",
            "Radiator Service", "Normal jobs", 41.8280, -71.4100, "2026-03-19", 12,
            description="Radiator service"),
        Job("SM8-30451", "400 Admiral St", "Providence", "RI", "03", "Federal Hill",
            "Radiator Replace & Refinish", "Normal jobs", 41.8340, -71.4350, "2026-03-01", 30,
            radiator_count=2, refinisher_location="Providence",
            description="Replace and refinish 2 radiators"),
        Job("SM8-40118", "88 Main St", "East Greenwich", "RI", "06", "East Greenwich",
            "Steam System Inspection", "Normal jobs", 41.6600, -71.4600, "2026-03-02", 29,
            description="Steam system inspection"),
        Job("SM8-40127", "55 Post Rd", "Warwick", "RI", "07", "Warwick",
            "Service Call", "Normal jobs", 41.7000, -71.4170, "2026-03-11", 20,
            description="Service call"),
        Job("SM8-40135", "12 Hope St", "Bristol", "RI", "08", "Bristol",
            "Boiler Maintenance", "Normal jobs", 41.6770, -71.2660, "2026-03-04", 27,
            description="Annual boiler maintenance"),
        Job("SM8-50101", "200 Thames St", "Newport", "RI", "09", "Newport",
            "New Equipment Installation Other Than Boiler", "Accepted Quotes",
            41.4880, -71.3130, "2026-02-10", 49,
            required_job_hours=4.0, avg_wait_2x_flag=True,
            total_job_amount=1400.0,
            description="New heat pump installation"),
        Job("SM8-50102", "90 Bellevue Ave", "Newport", "RI", "09", "Newport",
            "Castrads New Radiator(s)", "Normal jobs", 41.4750, -71.3100,
            "2026-03-07", 24, required_job_hours=3.5, radiator_count=6,
            description="New Castrads radiator install - 6 units"),
        Job("SM8-60201", "45 Main St", "Woonsocket", "RI", "10", "Woonsocket",
            "Service Call", "Normal jobs", 42.0030, -71.5150, "2026-02-25", 34,
            avg_wait_2x_flag=True,
            description="Service call - far north"),
        Job("SM8-60202", "33 Social St", "Woonsocket", "RI", "10", "Woonsocket",
            "Boiler Maintenance", "Normal jobs", 42.0010, -71.5120, "2026-03-13", 18,
            rebook_count_without_notes=1,
            description="Boiler maintenance - rebooked no notes"),
        Job("SM8-70301", "150 Main St", "Pawtucket", "RI", "11", "Pawtucket",
            "Vent / Trap / Repair / Piping Work", "Normal jobs", 41.8780, -71.3830,
            "2026-03-09", 22, required_job_hours=1.5,
            description="Vent repair"),
    ]
    techs = [
        Technician("T-01", "Mike",
                   ["boiler_service", "radiator", "steam_trap", "install", "overhaul"],
                   41.8180, -71.4350, ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        Technician("T-02", "Chris",
                   ["boiler_service", "radiator", "install", "steam_trap"],
                   41.8240, -71.4128, ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        Technician("T-03", "Dave",
                   ["boiler_service", "steam_trap", "radiator", "overhaul"],
                   41.8240, -71.4128, ["Mon", "Tue", "Wed", "Thu", "Fri"]),
    ]
    vehicles = [
        Vehicle("V-1", "service_truck",
                ["boiler_service", "steam_trap", "radiator", "install", "overhaul"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=500, cost_per_metre=0.00035, capacity=14),
        Vehicle("V-2", "radiator_van",
                ["radiator"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=400, cost_per_metre=0.00045, capacity=8),
        Vehicle("V-3", "service_truck",
                ["boiler_service", "steam_trap", "radiator", "install"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=500, cost_per_metre=0.00035, capacity=14),
        Vehicle("V-5", "service_truck",
                ["boiler_service", "steam_trap", "radiator", "overhaul"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=500, cost_per_metre=0.00035, capacity=14),
        Vehicle("V-4", "overflow",
                ["boiler_service", "steam_trap", "steam_system_inspection"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=500, cost_per_metre=0.00030, capacity=10),
    ]
    context = WeeklyContext(
        week_of="2026-04-06",
        season="Winter",
        include_v4=True,
        helpers_available=2,
    )
    exceptions = [
        WeeklyException("EX-2026-04-06-01", "2026-04-06", "Chris",
                        "Full technician-day block", "Friday", "PTO"),
        WeeklyException("EX-2026-04-06-02", "2026-04-06", "Dave",
                        "Full technician-day block", "Monday", "Training day"),
    ]
    area_rules = [
        AreaRule("V-4 eligibility", "Vehicle restriction",
                 "V-4 may carry steam system inspections, service calls, and boiler maintenance only."),
        AreaRule("V-2 radiator only", "Vehicle restriction",
                 "V-2 is dedicated to radiator work and radiator pick-up/delivery only."),
        AreaRule("Helper stays with tech", "Helper rule",
                 "Once a helper is assigned to a technician they stay together for the whole day."),
        AreaRule("No helper boiler maintenance", "Helper rule",
                 "Boiler maintenance does not require a helper by job type."),
        AreaRule("No helper service call", "Helper rule",
                 "Service calls do not require a helper by job type."),
        AreaRule("No helper steam inspection", "Helper rule",
                 "Steam system inspections do not require a helper by job type."),
        AreaRule("Winter route target", "Capacity rule",
                 "Winter: 4 booked + 2 standby per route. Possible 5th booked when backlog is high."),
        AreaRule("Summer route target", "Capacity rule",
                 "Summer: 3 booked + 2 standby per route."),
        AreaRule("Providence shop", "Area rule",
                 "Providence shop is an explicit routing factor. Use as start/end when optimizing routes."),
        AreaRule("Duplicate exception 15 Monticello", "Duplicate rule",
                 "Multiple radiator replacement slave jobs at 15 Monticello Providence must never be treated as duplicates."),
    ]

    wd = WeeklyData(jobs=jobs, technicians=techs, vehicles=vehicles,
                    exceptions=exceptions, context=context,
                    area_rules=area_rules)
    write_weekly_data(wd)
    return wd


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Create / read / validate NES weekly planning data files")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true",
                       help="Generate example CSV files in data/ folder")
    group.add_argument("--load", action="store_true",
                       help="Load existing CSVs and print summary")
    group.add_argument("--servicem8", action="store_true",
                       help="Pull live data from ServiceM8 API")
    args = parser.parse_args()

    if args.generate:
        wd = generate_example_data()
        print_summary(wd)

    elif args.load:
        if not DATA_DIR.exists():
            print(f"Data directory not found: {DATA_DIR}")
            print("Run with --generate first to create example files.")
            sys.exit(1)
        wd = load_weekly_data()
        print_summary(wd)

    elif args.servicem8:
        try:
            wd = pull_servicem8_weekly()
            print_summary(wd)
        except ValueError as exc:
            print(f"Configuration error: {exc}")
            sys.exit(1)
        except requests.RequestException as exc:
            print(f"ServiceM8 API error: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    main()
