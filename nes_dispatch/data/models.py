"""Domain data models — all pure @dataclass types used by the dispatch engine.

Aligned with the NES Python Scheduling Engine Build Spec v7 four-payload
input contract: Candidate Jobs, Weekly Context, Weekly Exceptions,
Lookup / Rules Data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Job categories (spec §3 / addendum Table 7) ────────────────────────────

FIXED_HOUR_CATEGORIES: dict[str, float] = {
    "Boiler Maintenance": 1.0,
    "Estimate": 1.0,
    "Go Back": 1.0,
    "New Boiler Visit": 1.0,
    "Radiator Pick-Up": 1.0,
    "Radiator Service": 1.0,
    "Service Call": 1.0,
    "Steam System Inspection": 1.0,
}

REQUIRED_HOURS_CATEGORIES: set[str] = {
    "Castrads New Radiator(s)",
    "Insulation",
    "New Equipment Installation Other Than Boiler",
    "Trap Service",
    "Vent / Trap / Repair / Piping Work",
}

RADIATOR_HOURS_CATEGORIES: set[str] = {
    "Radiator Refinishing",
    "Radiator Replace & Refinish",
    "Radiator Replacement",
}

ACCEPTED_QUOTE_CATEGORY = "Accepted Quotes"

ALL_CATEGORIES: set[str] = (
    set(FIXED_HOUR_CATEGORIES)
    | REQUIRED_HOURS_CATEGORIES
    | RADIATOR_HOURS_CATEGORIES
    | {ACCEPTED_QUOTE_CATEGORY}
)

# Queue values consumed by the engine (spec §4)
ELIGIBLE_QUEUES: set[str] = {
    "Priority",
    "Accepted Quotes",
    "Requested Scheduling",
    "Scheduling Preferences",
    "Normal jobs",
}
EXCLUDED_QUEUES: set[str] = {"Urgent", "On Hold"}


# ── Input models ────────────────────────────────────────────────────────────


@dataclass
class Job:
    """Candidate Jobs payload (spec §14.1 / addendum Table 3)."""
    job_id: str                          # Job Number / Job ID
    address: str                         # Service Address
    city: str                            # City
    state: str                           # State
    area_id: str                         # Normalized Area Number (2-digit)
    area_name: str                       # Area Name
    job_category: str                    # Job Category / Job Type
    queue: str                           # ServiceM8 Queue
    latitude: float                      # WGS-84 (Airtable-owned, Python fallback)
    longitude: float                     # WGS-84
    created_date: str                    # ISO date or empty if age supplied
    age_days: int                        # Computed Job Age (days)
    required_job_hours: Optional[float] = None   # Required Job Hours for Scheduling
    radiator_count: Optional[int] = None         # only for radiator work
    refinisher_location: str = ""                # only for radiator work
    avg_wait_2x_flag: bool = False               # 2x Average Wait Flag
    rebook_count_with_notes: int = 0             # rebook-age rule
    rebook_count_without_notes: int = 0          # rebook-age rule
    scheduling_preference: str = ""              # Scheduling Preference Detail (pending Amy)
    total_job_amount: Optional[float] = None       # $ amount for Accepted Quotes fallback
    description: str = ""

    # ── derived / back-compat aliases ───────────────────────────────────
    @property
    def route_type(self) -> str:
        """Map job_category → legacy route_type for downstream compatibility."""
        if self.job_category in RADIATOR_HOURS_CATEGORIES | {"Radiator Pick-Up", "Radiator Service"}:
            return "radiator"
        if self.job_category in {"New Equipment Installation Other Than Boiler",
                                  "Castrads New Radiator(s)"}:
            return "helper"
        return "normal"

    @property
    def helper_needed(self) -> bool:
        """Spec: Accepted Quotes always treated as Two-Man in initial build."""
        if self.queue == "Accepted Quotes":
            return True
        return self.job_category in {
            "New Equipment Installation Other Than Boiler",
            "Castrads New Radiator(s)",
        }

    @property
    def value(self) -> float:
        return self.planned_hours * 350.0

    @property
    def planned_hours(self) -> float:
        """Resolve planned hours per spec category-time table."""
        if self.job_category in FIXED_HOUR_CATEGORIES:
            return FIXED_HOUR_CATEGORIES[self.job_category]
        if self.job_category in REQUIRED_HOURS_CATEGORIES:
            return self.required_job_hours if self.required_job_hours else 1.0
        if self.job_category in RADIATOR_HOURS_CATEGORIES:
            # Radiator hours come from Airtable table; fall back to 1.0
            return self.required_job_hours if self.required_job_hours else 1.0
        if self.job_category == ACCEPTED_QUOTE_CATEGORY:
            if self.required_job_hours:
                return self.required_job_hours
            # Fallback: total job amount / 350, rounded up to next half-hour
            if self.total_job_amount and self.total_job_amount > 0:
                import math
                raw = self.total_job_amount / 350.0
                return math.ceil(raw * 2) / 2.0  # round up to next 0.5
            return 1.0
        return self.required_job_hours if self.required_job_hours else 1.0

    @property
    def service_time_min(self) -> float:
        return self.planned_hours * 60.0

    @property
    def status(self) -> str:
        """Status is now controlled by queue membership."""
        if self.queue in EXCLUDED_QUEUES:
            return "excluded"
        return "candidate"


@dataclass
class Technician:
    tech_id: str                         # route-slot identifier
    name: str                            # e.g. "Mike"
    skills: list[str]                    # capability tags
    home_lat: float                      # depot / base latitude
    home_lon: float                      # depot / base longitude
    available_days: list[str]            # base availability (before exceptions)


@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str                    # e.g. "service_truck", "radiator_van", "overflow"
    capability_tags: list[str]           # work-type restrictions
    available_days: list[str]            # base availability (before exceptions)
    speed_mpm: float = 500.0             # metres per minute (legacy; travel times from Google Maps)
    cost_per_metre: float = 0.0003       # $/m
    capacity: int = 14                   # max stops per route


@dataclass
class WeeklyContext:
    """Weekly Context payload (spec §14.1 / addendum Table 4)."""
    week_of: str                         # Monday date (ISO)
    season: str                          # "Winter" | "Summer"
    include_v4: bool                     # Include Van 4 this week?
    helpers_available: int = 2           # configurable default
    holiday_list: str = ""               # comma-separated holidays affecting the week


@dataclass
class WeeklyException:
    """Weekly Exceptions payload (addendum Table 5)."""
    exception_id: str
    week_of: str                         # links to scheduling week
    tech_or_slot: str                    # technician / route slot affected
    exception_type: str                  # "Full technician-day block" for initial build
    affected_day: str                    # "Monday" .. "Friday"
    notes: str = ""

    # ── back-compat aliases used by existing pipeline stages ────────────
    @property
    def scope_type(self) -> str:
        return "technician"

    @property
    def scope_id(self) -> str:
        return self.tech_or_slot

    @property
    def day(self) -> str:
        _map = {
            "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
            "Thursday": "Thu", "Friday": "Fri",
            "Mon": "Mon", "Tue": "Tue", "Wed": "Wed",
            "Thu": "Thu", "Fri": "Fri",
        }
        return _map.get(self.affected_day, self.affected_day)

    @property
    def effect_type(self) -> str:
        return "unavailable"

    @property
    def effect_value(self) -> str:
        return self.notes


@dataclass
class AreaRule:
    """Lookup / Rules Data payload (addendum Table 6)."""
    lookup_item: str                     # human-readable rule name
    lookup_type: str                     # e.g. "Vehicle restriction", "Area rule"
    rule_value: str                      # reference value consumed by Python
    active: bool = True


@dataclass
class WeeklyData:
    """Container returned by every loader — the planning engine's input."""
    jobs: list[Job] = field(default_factory=list)
    technicians: list[Technician] = field(default_factory=list)
    vehicles: list[Vehicle] = field(default_factory=list)
    exceptions: list[WeeklyException] = field(default_factory=list)
    context: Optional[WeeklyContext] = None
    area_rules: list[AreaRule] = field(default_factory=list)
    load_exclusions: list['Exclusion'] = field(default_factory=list)


# ── Output / intermediate models ────────────────────────────────────────────


@dataclass
class ScheduleAssignment:
    job_id: str
    tech_id: str
    vehicle_id: str
    day: str
    helper_required: bool = False      # spec §5: yes/no flag only, no named helper
    role: str = "assigned"              # "assigned" | "standby" | "anchor_hold"


@dataclass
class RouteResult:
    tech_id: str
    vehicle_id: str
    day: str
    visited_job_ids: list[str]         # ordered stop sequence
    dropped_job_ids: list[str]         # Phase-1-assigned but infeasible in Phase 2
    total_distance_m: float
    total_time_min: float
    helper_required: bool = False      # True if any job on route needs a helper
    standby_job_ids: list[str] = field(default_factory=list)  # spec §7: standby per route
    method: str = "nearest_neighbour"


@dataclass
class ReviewFlag:
    code: str                    # e.g. "DUP_ADDR", "ROUTE_DROP"
    severity: str                # "INFO" | "WARN" | "CRITICAL"
    message: str
    refs: dict = field(default_factory=dict)


@dataclass
class PreRouteCommunication:
    """Pre-Route Communications record (spec addendum Table 8).

    One row per week-build issue, surfaced before ServiceM8 transcription.
    """
    communication_id: str                           # unique row identifier
    communication_type: str                         # e.g. "Skipped Job", "Weak Route", "Duplicate Review"
    severity: str                                   # "Info" | "Warning" | "Action Needed"
    schedule_week: str                              # linked Schedule Week (week_of date)
    message: str                                    # human-readable message
    resolved: bool = False
    ryan_note: str = ""
    created_by_run: str = ""                        # run identifier for traceability
    job_number: str = ""                            # optional: tied to one job
    route_day: str = ""                             # optional: tied to a candidate route-day
    route_slot: str = ""                            # optional: tied to a candidate route slot
    what_needs_fixing: str = ""                     # plain-language fix request
    ai_suggested_action: str = ""                   # optional action guidance


@dataclass
class RouteCommunication:
    """Route Communications record (spec addendum Table 9).

    One row per route-specific issue, surfaced in the post-sync
    route/day/technician interface.
    """
    communication_id: str
    communication_type: str
    severity: str                                   # "Info" | "Warning" | "Action Needed"
    schedule_week: str
    message: str
    route_day: str                                  # required in post-sync interface
    route_slot: str                                 # technician or Van 4
    resolved: bool = False
    ryan_note: str = ""
    created_by_run: str = ""
    job_number: str = ""
    affected_window: str = ""                       # e.g. "7-8 first slot"
    outside_normal_parameters: bool = False          # flags weak-but-workable outcomes


@dataclass
class Exclusion:
    job_id: str
    reason_code: str             # e.g. "QUEUE_URGENT", "NO_ELIGIBLE_TRIPLE"
    detail: str
