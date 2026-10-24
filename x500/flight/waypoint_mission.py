"""Multirotor waypoint mission: checks, upload and read-back verification.

This is the first piece of the multirotor flight layer that the X500 proves and
Coyote is meant to reuse (owner decision 2026-10-21: the X500 is a
waypoint-autonomy aircraft only). It is written aircraft-agnostic: every
per-aircraft number arrives through :class:`MultirotorMissionLimits`, whose
values are **model inputs**, never constants in this file.

What it does
------------
1. :func:`check_mission` refuses a waypoint list (north/east metres and
   altitude above PX4 home) that leaves the advisory limits, instead of
   clipping it.
2. :func:`build_mission_items` converts a checked list to global coordinates
   around a home position.
3. :func:`compare_readback` compares the items PX4 returns on download with
   what was planned, field by field, so a truncated, reordered or altered
   mission is detected before anyone starts it.
4. :func:`upload_and_verify` performs upload -> download -> compare through a
   MAVSDK ``System``-like object. It never arms, starts the mission, or sends a
   flight command.

Authority boundary
------------------
PX4 stays authoritative for geofence, battery and link-loss failsafes, RTL,
mission execution and pilot override. The advisory limits here only make the
companion side more conservative and must be configured inside, never looser
than, the PX4 geofence and failsafe parameters.

Evidence status
---------------
Unit-tested with fake MAVSDK objects only. The MAVSDK conversion follows the
``mavsdk.mission.MissionItem`` constructor of MAVSDK-Python 3.17.2 (the version
recorded for the September 3 SITL runs), read from its source. Whether PX4 SITL
returns the uploaded items within the read-back tolerances is **not yet
observed**: no PX4 SITL run backs this module.

Projection
----------
Local north/east offsets are converted with a flat-Earth (equirectangular)
approximation, accurate to well under a centimetre at the
:data:`MAX_PROJECTION_DISTANCE_M` bound. Both directions use the same formula,
so the read-back comparison is self-consistent. A shared projection is a
candidate for ``shared/`` once a second multirotor consumer exists.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

EARTH_RADIUS_M = 6_371_000.0
# Bound on the flat-Earth approximation, independent of any aircraft limit.
MAX_PROJECTION_DISTANCE_M = 2_000.0
MAX_ABS_HOME_LATITUDE_DEG = 80.0


class MissionCheckError(ValueError):
    """The mission was refused before upload."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


class MissionReadbackError(RuntimeError):
    """The mission PX4 returned does not match the one uploaded."""

    def __init__(self, mismatches: Sequence[str]) -> None:
        self.mismatches = tuple(mismatches)
        super().__init__("; ".join(self.mismatches))


@dataclass(frozen=True)
class MultirotorMissionLimits:
    """Advisory companion-side mission limits. **Model inputs**, per aircraft.

    They are not measurements of any airframe and must sit inside the PX4
    geofence (``GF_MAX_HOR_DIST``/``GF_MAX_VER_DIST``) and speed parameters.
    """

    max_relative_altitude_m: float
    min_waypoint_altitude_m: float
    max_distance_from_home_m: float
    max_speed_m_s: float
    max_waypoints: int

    def validate(self) -> None:
        values = (
            self.max_relative_altitude_m,
            self.min_waypoint_altitude_m,
            self.max_distance_from_home_m,
            self.max_speed_m_s,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Mission limits must be finite numbers")
        if not 0.0 < self.min_waypoint_altitude_m < self.max_relative_altitude_m:
            raise ValueError("Need 0 < min waypoint altitude < max relative altitude")
        if self.max_relative_altitude_m > 120.0:
            raise ValueError("Max relative altitude above 120 m is not supported")
        if not 0.0 < self.max_distance_from_home_m <= MAX_PROJECTION_DISTANCE_M:
            raise ValueError(
                f"Max distance from home must be in (0, {MAX_PROJECTION_DISTANCE_M:.0f}] m"
            )
        if self.max_speed_m_s <= 0.0:
            raise ValueError("Max speed must be positive")
        if self.max_waypoints < 1:
            raise ValueError("Max waypoints must be at least 1")


@dataclass(frozen=True)
class ReadbackTolerances:
    """Allowed difference between planned and downloaded items.

    Defaults cover MAVLink integer lat/lon (1e-7 degree, about 1.1 cm) and
    float32 altitude/speed encoding. They are software tolerances, not flight
    accuracy claims.
    """

    horizontal_m: float = 0.10
    altitude_m: float = 0.05
    speed_m_s: float = 0.05


@dataclass(frozen=True)
class HomePosition:
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
class LocalWaypoint:
    """Waypoint relative to PX4 home: metres north/east, altitude above home."""

    north_m: float
    east_m: float
    relative_altitude_m: float
    speed_m_s: float
    is_fly_through: bool = True


@dataclass(frozen=True)
class GlobalWaypoint:
    """Planned or downloaded mission item in the fields this layer sets."""

    latitude_deg: float
    longitude_deg: float
    relative_altitude_m: float
    speed_m_s: float
    is_fly_through: bool


def local_to_global(home: HomePosition, north_m: float, east_m: float) -> tuple[float, float]:
    home.validate()
    lat = home.latitude_deg + math.degrees(north_m / EARTH_RADIUS_M)
    lon = home.longitude_deg + math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(math.radians(home.latitude_deg)))
    )
    return lat, lon


def global_to_local(
    home: HomePosition, latitude_deg: float, longitude_deg: float
) -> tuple[float, float]:
    home.validate()
    north = math.radians(latitude_deg - home.latitude_deg) * EARTH_RADIUS_M
    east = (
        math.radians(longitude_deg - home.longitude_deg)
        * EARTH_RADIUS_M
        * math.cos(math.radians(home.latitude_deg))
    )
    return north, east


def check_mission(waypoints: Sequence[LocalWaypoint], limits: MultirotorMissionLimits) -> list[str]:
    """Return every reason the mission is refused; an empty list means accepted."""

    limits.validate()
    if not waypoints:
        return ["mission has no waypoints"]
    reasons: list[str] = []
    if len(waypoints) > limits.max_waypoints:
        reasons.append(f"mission has {len(waypoints)} waypoints; limit is {limits.max_waypoints}")
    for index, wp in enumerate(waypoints):
        values = (wp.north_m, wp.east_m, wp.relative_altitude_m, wp.speed_m_s)
        if not all(math.isfinite(v) for v in values):
            reasons.append(f"waypoint {index} has non-finite values")
            continue
        distance = math.hypot(wp.north_m, wp.east_m)
        if distance > limits.max_distance_from_home_m:
            reasons.append(
                f"waypoint {index} is {distance:.1f} m from home; limit is "
                f"{limits.max_distance_from_home_m:.1f} m"
            )
        if wp.relative_altitude_m > limits.max_relative_altitude_m:
            reasons.append(
                f"waypoint {index} altitude {wp.relative_altitude_m:.1f} m exceeds "
                f"{limits.max_relative_altitude_m:.1f} m"
            )
        if wp.relative_altitude_m < limits.min_waypoint_altitude_m:
            reasons.append(
                f"waypoint {index} altitude {wp.relative_altitude_m:.1f} m is below "
                f"{limits.min_waypoint_altitude_m:.1f} m"
            )
        if not 0.0 < wp.speed_m_s <= limits.max_speed_m_s:
            reasons.append(
                f"waypoint {index} speed {wp.speed_m_s:.1f} m/s is outside "
                f"(0, {limits.max_speed_m_s:.1f}] m/s"
            )
    return reasons


def build_mission_items(
    waypoints: Sequence[LocalWaypoint],
    home: HomePosition,
    limits: MultirotorMissionLimits,
) -> tuple[GlobalWaypoint, ...]:
    """Check ``waypoints`` and convert them to global items, or raise MissionCheckError."""

    home.validate()
    reasons = check_mission(waypoints, limits)
    if reasons:
        raise MissionCheckError(reasons)
    items = []
    for wp in waypoints:
        lat, lon = local_to_global(home, wp.north_m, wp.east_m)
        items.append(
            GlobalWaypoint(
                latitude_deg=lat,
                longitude_deg=lon,
                relative_altitude_m=wp.relative_altitude_m,
                speed_m_s=wp.speed_m_s,
                is_fly_through=wp.is_fly_through,
            )
        )
    return tuple(items)


def compare_readback(
    planned: Sequence[GlobalWaypoint],
    downloaded: Sequence[Any],
    home: HomePosition,
    tolerances: ReadbackTolerances | None = None,
) -> list[str]:
    """Return every mismatch between planned and downloaded items.

    ``downloaded`` items need ``latitude_deg``, ``longitude_deg``,
    ``relative_altitude_m``, ``speed_m_s`` and ``is_fly_through`` attributes
    (MAVSDK ``MissionItem`` has them). Missing or non-finite values count as
    mismatches; nothing is assumed equal.
    """

    tol = tolerances or ReadbackTolerances()
    mismatches: list[str] = []
    if len(downloaded) != len(planned):
        mismatches.append(f"downloaded {len(downloaded)} items; uploaded {len(planned)}")
    for index, (want, got) in enumerate(zip(planned, downloaded, strict=False)):
        try:
            lat = float(got.latitude_deg)
            lon = float(got.longitude_deg)
            alt = float(got.relative_altitude_m)
            speed = float(got.speed_m_s)
            fly_through = got.is_fly_through
        except (AttributeError, TypeError, ValueError):
            mismatches.append(f"item {index} is missing a required field")
            continue
        if not all(math.isfinite(v) for v in (lat, lon, alt, speed)):
            mismatches.append(f"item {index} has non-finite values")
            continue
        want_n, want_e = global_to_local(home, want.latitude_deg, want.longitude_deg)
        got_n, got_e = global_to_local(home, lat, lon)
        horizontal = math.hypot(got_n - want_n, got_e - want_e)
        if horizontal > tol.horizontal_m:
            mismatches.append(f"item {index} position differs by {horizontal:.2f} m")
        if abs(alt - want.relative_altitude_m) > tol.altitude_m:
            mismatches.append(
                f"item {index} altitude {alt:.2f} m; planned {want.relative_altitude_m:.2f} m"
            )
        if abs(speed - want.speed_m_s) > tol.speed_m_s:
            mismatches.append(
                f"item {index} speed {speed:.2f} m/s; planned {want.speed_m_s:.2f} m/s"
            )
        if fly_through is not want.is_fly_through:
            mismatches.append(
                f"item {index} fly-through {fly_through!r}; planned {want.is_fly_through!r}"
            )
    return mismatches


def to_mavsdk_plan(items: Sequence[GlobalWaypoint], mission_module: Any) -> Any:
    """Build a ``MissionPlan`` from ``mission_module`` (``mavsdk.mission`` in use).

    Fields this layer does not control are left at "no action / unset" values.
    """

    item_cls = mission_module.MissionItem
    mavsdk_items = [
        item_cls(
            latitude_deg=item.latitude_deg,
            longitude_deg=item.longitude_deg,
            relative_altitude_m=item.relative_altitude_m,
            speed_m_s=item.speed_m_s,
            is_fly_through=item.is_fly_through,
            gimbal_pitch_deg=float("nan"),
            gimbal_yaw_deg=float("nan"),
            camera_action=item_cls.CameraAction.NONE,
            loiter_time_s=float("nan"),
            camera_photo_interval_s=float("nan"),
            acceptance_radius_m=float("nan"),
            yaw_deg=float("nan"),
            camera_photo_distance_m=float("nan"),
            vehicle_action=item_cls.VehicleAction.NONE,
        )
        for item in items
    ]
    return mission_module.MissionPlan(mavsdk_items)


async def upload_and_verify(
    drone: Any,
    items: Sequence[GlobalWaypoint],
    home: HomePosition,
    mission_module: Any,
    tolerances: ReadbackTolerances | None = None,
) -> int:
    """Upload ``items``, download them back and raise on any mismatch.

    Returns the number of verified items. Does not arm, start the mission or
    command flight. Callers must have refused non-simulation endpoints first.
    """

    if not items:
        raise MissionCheckError(["mission has no waypoints"])
    await drone.mission.upload_mission(to_mavsdk_plan(items, mission_module))
    downloaded = await drone.mission.download_mission()
    mismatches = compare_readback(
        items, list(getattr(downloaded, "mission_items", []) or []), home, tolerances
    )
    if mismatches:
        raise MissionReadbackError(mismatches)
    return len(items)
