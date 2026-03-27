"""Domain data models — all pure @dataclass types used by the dispatch engine."""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Input models ────────────────────────────────────────────────────────────


@dataclass
class Job:
    job_id: str
    address: str
    latitude: float              # WGS-84
    longitude: float             # WGS-84
    area_id: str                 # ∈ A
    route_type: str              # "normal" | "radiator" | "nh_overnight" | "helper"
    helper_needed: bool          # h_j — True if two-man job
    age_days: int                # α_j — days since creation
    value: float                 # w_j — base revenue ($)
    service_time_min: float      # τ_j — on-site duration (minutes)
    status: str                  # "candidate" | "excluded" | "assigned"
    description: str = ""


@dataclass
class Technician:
    tech_id: str
    name: str
    skills: list[str]            # skill_t
    home_lat: float              # y_t
    home_lon: float              # x_t
    available_days: list[str]    # D_t (before exceptions)


@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str
    capability_tags: list[str]   # cap_k
    available_days: list[str]    # D_k (before exceptions)
    speed_mpm: float             # v_k (metres per minute)
    cost_per_metre: float        # c_k ($/m)
    capacity: int                # Q_k (max stops per route)


@dataclass
class WeeklyException:
    exception_id: str
    scope_type: str              # "technician" | "vehicle"
    scope_id: str                # references tech_id or vehicle_id
    day: str                     # "Mon" .. "Fri"
    effect_type: str             # "unavailable" | "partial"
    effect_value: str            # reason / detail


@dataclass
class WeeklyData:
    jobs: list[Job]
    technicians: list[Technician]
    vehicles: list[Vehicle]
    exceptions: list[WeeklyException]


# ── Output / intermediate models ────────────────────────────────────────────


@dataclass
class ScheduleAssignment:
    job_id: str
    tech_id: str
    vehicle_id: str
    day: str
    helper_tech_id: str | None = None  # set for J^H jobs


@dataclass
class RouteResult:
    tech_id: str
    vehicle_id: str
    day: str
    visited_job_ids: list[str]         # ordered stop sequence
    dropped_job_ids: list[str]         # Phase-1-assigned but infeasible in Phase 2
    total_distance_m: float
    total_time_min: float
    method: str = "nearest_neighbour"


@dataclass
class ReviewFlag:
    code: str                    # e.g. "DUP_ADDR", "ROUTE_DROP"
    severity: str                # "INFO" | "WARN" | "CRITICAL"
    message: str
    refs: dict = field(default_factory=dict)


@dataclass
class Exclusion:
    job_id: str
    reason_code: str             # e.g. "SKILL_MISMATCH", "CLUSTER_RADIUS"
    detail: str
