#!/usr/bin/env python3
"""
weekly_data.py — Create, read, and validate weekly planning data files
for the NES dispatch-routing engine.

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
}

SERVICEM8_API = "https://api.servicem8.com/api_1.0"

ROUTE_TYPES = {"normal", "radiator", "nh_overnight", "helper"}
VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri"}

# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Job:
    job_id: str
    address: str
    latitude: float
    longitude: float
    area_id: str
    route_type: str  # normal | radiator | nh_overnight | helper
    helper_needed: bool
    age_days: int
    value: float
    service_time_min: float  # on-site service duration (minutes)
    status: str  # candidate | excluded | assigned
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
    speed_mpm: float  # metres per minute
    cost_per_metre: float  # $/m
    capacity: int  # max stops per route


@dataclass
class WeeklyException:
    exception_id: str
    scope_type: str  # technician | vehicle
    scope_id: str
    day: str
    effect_type: str  # unavailable | partial
    effect_value: str


@dataclass
class WeeklyData:
    """Container returned by every loader — the planning engine's input."""
    jobs: List[Job] = field(default_factory=list)
    technicians: List[Technician] = field(default_factory=list)
    vehicles: List[Vehicle] = field(default_factory=list)
    exceptions: List[WeeklyException] = field(default_factory=list)


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


def load_jobs(path: Path) -> List[Job]:
    jobs = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            jobs.append(Job(
                job_id=row["job_id"],
                address=row["address"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                area_id=row["area_id"],
                route_type=row["route_type"],
                helper_needed=bool(int(row["helper_needed"])),
                age_days=int(row["age_days"]),
                value=float(row["value"]),
                service_time_min=float(row.get("service_time_min", 30)),
                status=row["status"],
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


def load_exceptions(path: Path) -> List[WeeklyException]:
    exceptions = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            exceptions.append(WeeklyException(
                exception_id=row["exception_id"],
                scope_type=row["scope_type"],
                scope_id=row["scope_id"],
                day=row["day"],
                effect_type=row["effect_type"],
                effect_value=row["effect_value"],
            ))
    return exceptions


def load_weekly_data(data_dir: Optional[Path] = None) -> WeeklyData:
    """Load all four CSV files from *data_dir* and return a WeeklyData."""
    d = data_dir or DATA_DIR
    return WeeklyData(
        jobs=load_jobs(d / "example_jobs.csv"),
        technicians=load_technicians(d / "example_technicians.csv"),
        vehicles=load_vehicles(d / "example_vehicles.csv"),
        exceptions=load_exceptions(d / "example_weekly_exceptions.csv"),
    )


# ---------------------------------------------------------------------------
# CSV writers (used by --generate and --servicem8)
# ---------------------------------------------------------------------------

def write_jobs(jobs: List[Job], path: Path) -> None:
    cols = ["job_id", "address", "latitude", "longitude", "area_id",
            "route_type", "helper_needed", "age_days", "value",
            "service_time_min", "status", "description"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for j in jobs:
            row = asdict(j)
            row["helper_needed"] = int(row["helper_needed"])
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


def write_exceptions(exceptions: List[WeeklyException], path: Path) -> None:
    cols = ["exception_id", "scope_type", "scope_id", "day",
            "effect_type", "effect_value"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for e in exceptions:
            w.writerow(asdict(e))


def write_weekly_data(wd: WeeklyData, data_dir: Optional[Path] = None) -> None:
    d = data_dir or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    write_jobs(wd.jobs, d / "example_jobs.csv")
    write_technicians(wd.technicians, d / "example_technicians.csv")
    write_vehicles(wd.vehicles, d / "example_vehicles.csv")
    write_exceptions(wd.exceptions, d / "example_weekly_exceptions.csv")
    print(f"Wrote {len(wd.jobs)} jobs, {len(wd.technicians)} techs, "
          f"{len(wd.vehicles)} vehicles, {len(wd.exceptions)} exceptions → {d}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(wd: WeeklyData) -> List[str]:
    """Return a list of warning/error strings. Empty list = valid."""
    issues: List[str] = []

    tech_ids = {t.tech_id for t in wd.technicians}
    vehicle_ids = {v.vehicle_id for v in wd.vehicles}

    for j in wd.jobs:
        if j.route_type not in ROUTE_TYPES:
            issues.append(f"{j.job_id}: unknown route_type '{j.route_type}'")
        if j.value < 0:
            issues.append(f"{j.job_id}: negative value {j.value}")

    for ex in wd.exceptions:
        if ex.scope_type == "technician" and ex.scope_id not in tech_ids:
            issues.append(f"{ex.exception_id}: unknown tech {ex.scope_id}")
        if ex.scope_type == "vehicle" and ex.scope_id not in vehicle_ids:
            issues.append(f"{ex.exception_id}: unknown vehicle {ex.scope_id}")
        if ex.day not in VALID_DAYS:
            issues.append(f"{ex.exception_id}: invalid day '{ex.day}'")

    # Duplicate-address detection
    addr_groups: dict = {}
    for j in wd.jobs:
        addr_groups.setdefault(j.address, []).append(j.job_id)
    for addr, ids in addr_groups.items():
        if len(ids) > 1:
            issues.append(f"Duplicate address '{addr}': {ids}")

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


def _classify_route_type(sm8_job: dict) -> str:
    """Heuristic classification from ServiceM8 job fields."""
    desc = (sm8_job.get("description") or "").lower()
    cat = (sm8_job.get("job_category_uuid") or "").lower()
    if "radiator" in desc:
        return "radiator"
    if "overnight" in desc or "nh" in cat:
        return "nh_overnight"
    if "helper" in desc or "install" in desc:
        return "helper"
    return "normal"


def _needs_helper(sm8_job: dict) -> bool:
    desc = (sm8_job.get("description") or "").lower()
    return "helper" in desc or "two-man" in desc or "install" in desc


def fetch_servicem8_jobs() -> List[Job]:
    """Pull active jobs from ServiceM8 and convert to Job dataclass list."""
    raw_jobs = _sm8_get("job.json")
    jobs: List[Job] = []
    for idx, rj in enumerate(raw_jobs, start=1):
        status_raw = (rj.get("status") or "").lower()
        if status_raw in ("completed", "cancelled", "deleted"):
            continue

        lat = rj.get("geo_latitude")
        lon = rj.get("geo_longitude")
        if lat is None or lon is None:
            # Try job address geocoding fallback fields
            lat = rj.get("address_latitude")
            lon = rj.get("address_longitude")
        if lat is None or lon is None:
            continue

        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue

        rt = _classify_route_type(rj)
        jobs.append(Job(
            job_id=rj.get("uuid", f"SM8-{idx:04d}"),
            address=rj.get("job_address", ""),
            latitude=lat,
            longitude=lon,
            area_id=rj.get("area_uuid", "unknown"),
            route_type=rt,
            helper_needed=_needs_helper(rj),
            age_days=0,  # compute externally from created_date if needed
            value=float(rj.get("total_invoice_amount") or 0),
            service_time_min=float(rj.get("estimated_duration") or 30),
            status="candidate",
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

    # Vehicles and exceptions are Airtable-managed; use existing files or empty
    d = data_dir or DATA_DIR
    vehicles: List[Vehicle] = []
    exceptions: List[WeeklyException] = []
    veh_path = d / "example_vehicles.csv"
    exc_path = d / "example_weekly_exceptions.csv"
    if veh_path.exists():
        vehicles = load_vehicles(veh_path)
    if exc_path.exists():
        exceptions = load_exceptions(exc_path)

    wd = WeeklyData(jobs=jobs, technicians=techs,
                    vehicles=vehicles, exceptions=exceptions)
    write_weekly_data(wd, d)
    return wd


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(wd: WeeklyData) -> None:
    print("=" * 60)
    print("WEEKLY PLANNING DATA SUMMARY")
    print("=" * 60)

    print(f"\nJobs: {len(wd.jobs)}")
    by_type: dict = {}
    for j in wd.jobs:
        by_type.setdefault(j.route_type, []).append(j)
    for rt, jlist in sorted(by_type.items()):
        total_val = sum(j.value for j in jlist)
        print(f"  {rt:15s}  {len(jlist):3d} jobs  ${total_val:,.0f} total value")

    print(f"\nTechnicians: {len(wd.technicians)}")
    for t in wd.technicians:
        print(f"  {t.tech_id}  {t.name:20s}  days={','.join(t.available_days)}")

    print(f"\nVehicles: {len(wd.vehicles)}")
    for v in wd.vehicles:
        print(f"  {v.vehicle_id}  {v.vehicle_type:18s}  "
              f"cap={v.capacity}  v={v.speed_mpm}m/min  c=${v.cost_per_metre}/m  "
              f"days={','.join(v.available_days)}")

    print(f"\nWeekly Exceptions: {len(wd.exceptions)}")
    for ex in wd.exceptions:
        print(f"  {ex.exception_id}  {ex.scope_type}:{ex.scope_id}  "
              f"{ex.day}  {ex.effect_type} ({ex.effect_value})")

    issues = validate(wd)
    if issues:
        print(f"\nValidation issues ({len(issues)}):")
        for issue in issues:
            print(f"  ⚠ {issue}")
    else:
        print("\n✓ All validation checks passed.")

    # Distance summary from first technician to all jobs
    if wd.technicians and wd.jobs:
        t0 = wd.technicians[0]
        dists = [(j.job_id, haversine(t0.home_lat, t0.home_lon,
                                       j.latitude, j.longitude))
                 for j in wd.jobs]
        dists.sort(key=lambda x: x[1])
        print(f"\nDistances from {t0.name} ({t0.tech_id}):")
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
        Job("J-001", "123 Main St Concord NH", 43.2081, -71.5376, "Area-1",
            "normal", False, 14, 250.0, 30, "candidate", "Annual boiler service"),
        Job("J-002", "456 Elm St Manchester NH", 42.9956, -71.4548, "Area-2",
            "normal", False, 7, 180.0, 25, "candidate", "Steam trap inspection"),
        Job("J-003", "789 Broadway Nashua NH", 42.7654, -71.4676, "Area-3",
            "normal", False, 21, 320.0, 45, "candidate", "Radiator valve replacement"),
        Job("J-004", "12 Oak Ave Concord NH", 43.2120, -71.5420, "Area-1",
            "normal", False, 3, 150.0, 20, "candidate", "Thermostat calibration"),
        Job("J-005", "88 Pine Rd Derry NH", 42.8806, -71.3273, "Area-2",
            "normal", False, 30, 410.0, 60, "candidate", "Full system flush"),
        Job("J-006", "34 Maple Dr Bedford NH", 42.9465, -71.5158, "Area-2",
            "normal", False, 12, 220.0, 25, "candidate", "Pressure relief valve test"),
        Job("J-007", "56 Cedar Ln Merrimack NH", 42.8615, -71.4935, "Area-3",
            "normal", False, 9, 190.0, 30, "candidate", "Zone valve repair"),
        Job("J-008", "901 River Rd Bow NH", 43.1328, -71.5384, "Area-1",
            "normal", False, 17, 275.0, 40, "candidate", "Expansion tank replacement"),
        Job("J-009", "22 Church St Keene NH", 42.9339, -72.2783, "Area-4",
            "nh_overnight", False, 45, 520.0, 90, "candidate", "Full boiler overhaul"),
        Job("J-010", "67 State St Portsmouth NH", 43.0718, -70.7626, "Area-5",
            "normal", False, 10, 200.0, 30, "candidate", "Annual inspection"),
        Job("J-011", "145 South St Concord NH", 43.2003, -71.5340, "Area-1",
            "radiator", False, 8, 350.0, 50, "candidate", "Radiator run - 3 units"),
        Job("J-012", "78 North Main St Manchester NH", 43.0012, -71.4620, "Area-2",
            "normal", False, 25, 300.0, 35, "candidate", "Steam pipe insulation"),
        Job("J-013", "33 Lake Ave Laconia NH", 43.5278, -71.4714, "Area-6",
            "normal", False, 40, 380.0, 45, "candidate", "Boiler efficiency test"),
        Job("J-014", "55 Market St Portsmouth NH", 43.0770, -70.7580, "Area-5",
            "normal", False, 5, 170.0, 20, "candidate", "Thermostat replacement"),
        Job("J-015", "210 Central St Franklin NH", 43.4453, -71.6474, "Area-6",
            "normal", False, 18, 260.0, 35, "candidate", "Zone control repair"),
        Job("J-016", "19 Depot St Concord NH", 43.2075, -71.5390, "Area-1",
            "helper", True, 11, 450.0, 120, "candidate", "Boiler install assist"),
        Job("J-017", "400 Amherst St Nashua NH", 42.7710, -71.4910, "Area-3",
            "normal", False, 6, 185.0, 25, "candidate", "Pipe leak repair"),
        Job("J-018", "88 Hanover St Manchester NH", 42.9910, -71.4630, "Area-2",
            "normal", False, 33, 340.0, 45, "candidate", "Steam system balancing"),
        Job("J-019", "12 Main St Peterborough NH", 42.8706, -71.9517, "Area-4",
            "nh_overnight", False, 50, 480.0, 90, "candidate", "Full system overhaul"),
        Job("J-020", "300 Daniel Webster Hwy Merrimack NH", 42.8580, -71.5010, "Area-3",
            "normal", False, 15, 230.0, 35, "candidate", "Pump replacement"),
        Job("J-021", "145 South St Concord NH", 43.2003, -71.5340, "Area-1",
            "normal", False, 20, 200.0, 30, "candidate", "Follow-up valve check"),
        Job("J-022", "77 Pleasant St Concord NH", 43.2065, -71.5355, "Area-1",
            "radiator", False, 13, 360.0, 50, "candidate", "Radiator run - 2 units"),
        Job("J-023", "50 West St Keene NH", 42.9345, -72.2800, "Area-4",
            "normal", False, 28, 310.0, 40, "candidate", "Annual maintenance"),
        Job("J-024", "1010 Elm St Manchester NH", 42.9870, -71.4545, "Area-2",
            "helper", True, 4, 500.0, 120, "candidate", "Boiler replacement"),
        Job("J-025", "65 Bridge St Manchester NH", 42.9990, -71.4580, "Area-2",
            "normal", False, 22, 290.0, 35, "candidate", "Condensate return repair"),
    ]
    techs = [
        Technician("T-01", "Mike Sullivan",
                   ["boiler_service", "radiator", "steam_trap", "install"],
                   43.2081, -71.5376, ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        Technician("T-02", "Dave Patel",
                   ["boiler_service", "steam_trap", "zone_valve", "pipe_repair"],
                   42.9956, -71.4548, ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        Technician("T-03", "Chris O'Brien",
                   ["boiler_service", "radiator", "install", "overhaul"],
                   43.0718, -70.7626, ["Mon", "Tue", "Wed", "Thu"]),
        Technician("T-04", "Sam Torres",
                   ["boiler_service", "steam_trap", "pump", "pipe_repair"],
                   42.7654, -71.4676, ["Mon", "Tue", "Wed", "Thu", "Fri"]),
    ]
    vehicles = [
        Vehicle("V-2", "radiator_van",
                ["radiator", "install", "overhaul"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=400, cost_per_metre=0.00045, capacity=8),
        Vehicle("V-4", "capacity_switch",
                ["boiler_service", "steam_trap"],
                ["Mon", "Wed", "Fri"],
                speed_mpm=500, cost_per_metre=0.00030, capacity=10),
        Vehicle("V-5", "service_truck",
                ["boiler_service", "steam_trap", "zone_valve", "pipe_repair", "pump"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=500, cost_per_metre=0.00035, capacity=14),
        Vehicle("V-6", "service_truck",
                ["boiler_service", "steam_trap", "zone_valve", "pipe_repair", "pump"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=500, cost_per_metre=0.00035, capacity=14),
        Vehicle("V-7", "service_truck",
                ["boiler_service", "radiator", "install"],
                ["Mon", "Tue", "Wed", "Thu", "Fri"],
                speed_mpm=450, cost_per_metre=0.00040, capacity=12),
    ]
    exceptions = [
        WeeklyException("EX-01", "technician", "T-03", "Fri",
                        "unavailable", "PTO"),
        WeeklyException("EX-02", "vehicle", "V-4", "Tue",
                        "unavailable", "maintenance"),
        WeeklyException("EX-03", "vehicle", "V-4", "Thu",
                        "unavailable", "maintenance"),
        WeeklyException("EX-04", "technician", "T-01", "Wed",
                        "partial", "boiler_install_3hrs"),
        WeeklyException("EX-05", "technician", "T-02", "Mon",
                        "unavailable", "training"),
    ]

    wd = WeeklyData(jobs=jobs, technicians=techs,
                    vehicles=vehicles, exceptions=exceptions)
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
