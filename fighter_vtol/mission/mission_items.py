"""Convert a checked Fighter survey plan into geodetic mission-item specs.

:func:`fighter_vtol.mission.survey_plan.plan_survey` works in local metres
relative to PX4 home. A PX4 mission upload needs latitude/longitude, a
relative altitude and a vehicle action per item. This module performs that
conversion deterministically and refuses plans whose phase structure is not
the one the planner produces, so a hand-edited or truncated plan cannot become
an upload (for example a fixed-wing waypoint before the forward transition, or
a landing without a back transition).

It imports no MAVSDK and sends nothing. The :class:`VehicleAction` values are
named after MAVSDK ``MissionItem.VehicleAction`` members so a later SITL
adapter can map them one-to-one, but that mapping, and how PX4 executes these
items on a VTOL, are **not verified** here: no PX4 VTOL SITL run backs this
module. PX4 keeps transitions, fixed-wing guidance, geofence, failsafes, RTL
and pilot override.

Projection
----------
:func:`local_to_global` uses the spherical azimuthal-equidistant projection
(Earth radius 6 371 000 m) in the form PX4's ``MapProjection`` (``lib/geo``)
uses for its local frame, as understood from that source; it has not been
compared numerically with a PX4 build. :func:`global_to_local` is its inverse.
The projection is refused beyond :data:`MAX_PROJECTION_DISTANCE_M` from home
and above :data:`MAX_ABS_HOME_LATITUDE_DEG`.

Model inputs: none of the numbers here describe the Fighter airframe. The
fly-through choice per item (pass through survey/approach waypoints, stop at
takeoff/transition/landing items) is a development default, not a tuned PX4
setting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from fighter_vtol.mission.survey_plan import Phase, PlanItem, SurveyPlan

EARTH_RADIUS_M = 6_371_000.0
# Survey plans are capped well below this by SurveyLimits; this bound only
# keeps the flat local frame from being misused for long distances.
MAX_PROJECTION_DISTANCE_M = 10_000.0
MAX_ABS_HOME_LATITUDE_DEG = 80.0


class MissionExportError(ValueError):
    """The plan cannot be converted into mission items."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(reasons))


class VehicleAction(Enum):
    """Per-item action, named after MAVSDK ``MissionItem.VehicleAction`` members."""

    NONE = "NONE"
    TAKEOFF = "TAKEOFF"
    LAND = "LAND"
    TRANSITION_TO_FW = "TRANSITION_TO_FW"
    TRANSITION_TO_MC = "TRANSITION_TO_MC"


_ACTION_FOR_PHASE = {
    Phase.VTOL_TAKEOFF: VehicleAction.TAKEOFF,
    Phase.TRANSITION_TO_FW: VehicleAction.TRANSITION_TO_FW,
    Phase.FW_WAYPOINT: VehicleAction.NONE,
    Phase.TRANSITION_TO_MC: VehicleAction.TRANSITION_TO_MC,
    Phase.VTOL_LAND: VehicleAction.LAND,
}


@dataclass(frozen=True)
class HomePosition:
    """PX4 home used as the origin of the plan's local frame."""

    latitude_deg: float
    longitude_deg: float

    def validate(self) -> None:
        if not (math.isfinite(self.latitude_deg) and math.isfinite(self.longitude_deg)):
            raise ValueError("Home latitude/longitude must be finite numbers")
        if abs(self.latitude_deg) > MAX_ABS_HOME_LATITUDE_DEG:
            raise ValueError(
                f"Home latitude beyond +/-{MAX_ABS_HOME_LATITUDE_DEG} degrees is not supported"
            )
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("Home longitude must be between -180 and 180 degrees")


@dataclass(frozen=True)
class MissionItemSpec:
    """One proposed mission item in global coordinates; not an upload."""

    latitude_deg: float
    longitude_deg: float
    relative_altitude_m: float
    is_fly_through: bool
    vehicle_action: VehicleAction
    role: str
    line_index: int | None = None


def local_to_global(home: HomePosition, north_m: float, east_m: float) -> tuple[float, float]:
    """Project local north/east metres from ``home`` to (latitude, longitude) degrees."""

    home.validate()
    if not (math.isfinite(north_m) and math.isfinite(east_m)):
        raise ValueError("Local coordinates must be finite numbers")
    distance = math.hypot(north_m, east_m)
    if distance > MAX_PROJECTION_DISTANCE_M:
        raise ValueError(
            f"Point {distance:.1f} m from home exceeds projection limit "
            f"{MAX_PROJECTION_DISTANCE_M:.0f} m"
        )

    lat0 = math.radians(home.latitude_deg)
    lon0 = math.radians(home.longitude_deg)
    x_rad = north_m / EARTH_RADIUS_M
    y_rad = east_m / EARTH_RADIUS_M
    c = math.hypot(x_rad, y_rad)
    if c == 0.0:
        return home.latitude_deg, home.longitude_deg

    sin_c, cos_c = math.sin(c), math.cos(c)
    sin_lat0, cos_lat0 = math.sin(lat0), math.cos(lat0)
    lat = math.asin(cos_c * sin_lat0 + x_rad * sin_c * cos_lat0 / c)
    lon = lon0 + math.atan2(y_rad * sin_c, c * cos_lat0 * cos_c - x_rad * sin_lat0 * sin_c)
    lon_deg = (math.degrees(lon) + 180.0) % 360.0 - 180.0
    return math.degrees(lat), lon_deg


def global_to_local(
    home: HomePosition, latitude_deg: float, longitude_deg: float
) -> tuple[float, float]:
    """Inverse of :func:`local_to_global`: (north_m, east_m) of a point from ``home``."""

    home.validate()
    if not (math.isfinite(latitude_deg) and math.isfinite(longitude_deg)):
        raise ValueError("Latitude/longitude must be finite numbers")

    lat0 = math.radians(home.latitude_deg)
    lon0 = math.radians(home.longitude_deg)
    lat = math.radians(latitude_deg)
    d_lon = math.radians(longitude_deg) - lon0
    sin_lat0, cos_lat0 = math.sin(lat0), math.cos(lat0)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    cos_d_lon = math.cos(d_lon)

    arg = max(-1.0, min(1.0, sin_lat0 * sin_lat + cos_lat0 * cos_lat * cos_d_lon))
    c = math.acos(arg)
    k = 1.0 if abs(c) < 1e-12 else c / math.sin(c)
    north = k * (cos_lat0 * sin_lat - sin_lat0 * cos_lat * cos_d_lon) * EARTH_RADIUS_M
    east = k * cos_lat * math.sin(d_lon) * EARTH_RADIUS_M
    return north, east


def check_plan_structure(items: tuple[PlanItem, ...] | list[PlanItem]) -> list[str]:
    """Return reasons the item sequence is not takeoff, transition, FW legs, transition, land."""

    reasons: list[str] = []
    if len(items) < 5:
        return [f"plan has {len(items)} items; at least 5 are required"]

    expected_head = (Phase.VTOL_TAKEOFF, Phase.TRANSITION_TO_FW)
    expected_tail = (Phase.TRANSITION_TO_MC, Phase.VTOL_LAND)
    head = tuple(item.phase for item in items[:2])
    tail = tuple(item.phase for item in items[-2:])
    if head != expected_head:
        reasons.append(
            "plan must start with VTOL takeoff then forward transition, got "
            + ", ".join(p.value for p in head)
        )
    if tail != expected_tail:
        reasons.append(
            "plan must end with back transition then VTOL landing, got "
            + ", ".join(p.value for p in tail)
        )
    middle = items[2:-2]
    for index, item in enumerate(middle, start=2):
        if item.phase is not Phase.FW_WAYPOINT:
            reasons.append(
                f"item {index} ({item.role}) is {item.phase.value}; only fixed-wing "
                "waypoints are allowed between the transitions"
            )
            break
    if not middle:
        reasons.append("plan has no fixed-wing waypoints between the transitions")

    for index, item in enumerate(items):
        if not all(math.isfinite(v) for v in (item.north_m, item.east_m, item.altitude_m)):
            reasons.append(f"item {index} ({item.role}) has non-finite coordinates")
            break

    first, last = items[0], items[-1]
    for label, item in (("takeoff", first), ("landing", last)):
        if item.phase in (Phase.VTOL_TAKEOFF, Phase.VTOL_LAND) and (
            abs(item.north_m) > 1e-6 or abs(item.east_m) > 1e-6
        ):
            reasons.append(f"VTOL {label} must be at home (0, 0)")
    if last.phase is Phase.VTOL_LAND and abs(last.altitude_m) > 1e-6:
        reasons.append("VTOL landing altitude must be 0 m above home")
    for index, item in enumerate(items[:-1]):
        if item.altitude_m <= 0.0:
            reasons.append(
                f"item {index} ({item.role}) altitude {item.altitude_m:.1f} m must be "
                "above home before the landing item"
            )
            break
    return reasons


def build_mission_items(plan: SurveyPlan, home: HomePosition) -> tuple[MissionItemSpec, ...]:
    """Convert ``plan`` to global mission-item specs or raise :class:`MissionExportError`."""

    home.validate()
    reasons = check_plan_structure(plan.items)
    if reasons:
        raise MissionExportError(reasons)

    specs: list[MissionItemSpec] = []
    for item in plan.items:
        try:
            lat, lon = local_to_global(home, item.north_m, item.east_m)
        except ValueError as exc:
            raise MissionExportError([f"{item.role}: {exc}"]) from exc
        action = _ACTION_FOR_PHASE[item.phase]
        specs.append(
            MissionItemSpec(
                latitude_deg=lat,
                longitude_deg=lon,
                relative_altitude_m=item.altitude_m,
                # Pass through survey and approach waypoints; stop at items that
                # carry a takeoff, transition or landing action.
                is_fly_through=action is VehicleAction.NONE,
                vehicle_action=action,
                role=item.role,
                line_index=item.line_index,
            )
        )
    return tuple(specs)
