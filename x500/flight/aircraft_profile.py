"""Real-aircraft settings profile built only from sourced model inputs.

Part of the multirotor flight layer that the X500 proves and Coyote is meant to
reuse (owner decision 2026-10-21). Aircraft-agnostic: an aircraft supplies a
mapping of field name -> :class:`ModelInput`, and this module turns it into the
same settings objects the SITL scripts use today.

Gap it closes
-------------
Every number the flight layer uses (``settings.py``, ``monitor_settings.py``)
is a SITL development placeholder, and nothing in the code stops those
placeholders from being reused for a real aircraft by default. This module
keeps a real-aircraft profile separate: it refuses to produce settings until
every field has a value **and** a recorded source of a kind allowed for that
field (an owner choice, a bench measurement or a flight measurement, with a
reference such as a decision date or log name). SITL placeholders and
catalogue claims are never accepted as a real-aircraft source.

It also checks one calculation the separate settings objects cannot: the
monitor's mission budget plus the return-watch budget must fit inside the
measured usable flight time. That is a consistency check between model inputs,
not an endurance claim: nominal battery energy is not safe endurance, and the
usable flight time must come from the aircraft's own logged flights.

Authority boundary
------------------
Pure configuration code. It never connects to a vehicle, reads or sets PX4
parameters, or selects a value. Passing it means only that the inputs are
complete, sourced and mutually consistent; PX4 geofence, failsafe, RTL and
pilot override remain authoritative, and ``px4_limits`` still checks the result
against the PX4 parameters at run time. No entry point uses this profile yet:
adding a real-aircraft connection path is an owner decision.

Evidence status
---------------
Unit-tested only. No real-aircraft profile is complete in this repository.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from .mission_monitor import MonitorSettings
from .preflight import PreflightLimits
from .return_monitor import ReturnSettings
from .waypoint_mission import MultirotorMissionLimits


class InputSource(Enum):
    """Where a model-input value came from."""

    SITL_PLACEHOLDER = "sitl_placeholder"
    CATALOGUE_CLAIM = "catalogue_claim"
    OWNER_CHOICE = "owner_choice"
    BENCH_MEASUREMENT = "bench_measurement"
    FLIGHT_MEASUREMENT = "flight_measurement"


@dataclass(frozen=True)
class ModelInput:
    """One profile value with its provenance. ``None`` means not yet filled in."""

    value: float | int | None = None
    source: InputSource | None = None
    reference: str = ""  # decision date, bench record or flight-log name
    note: str = ""  # what evidence fills it; never used in a decision


@dataclass(frozen=True)
class FieldSpec:
    unit: str
    allowed_sources: frozenset[InputSource]
    integer: bool = False


_OWNER = frozenset({InputSource.OWNER_CHOICE})
_FLIGHT = frozenset({InputSource.FLIGHT_MEASUREMENT})
# A time budget is a choice informed by logged runs, or the logged value itself.
_TIMING = frozenset({InputSource.OWNER_CHOICE, InputSource.FLIGHT_MEASUREMENT})
_LINK = frozenset(
    {InputSource.OWNER_CHOICE, InputSource.BENCH_MEASUREMENT, InputSource.FLIGHT_MEASUREMENT}
)

PROFILE_FIELDS: dict[str, FieldSpec] = {
    # Mission limits: owner choices that must sit inside the PX4 geofence and
    # speed parameters (checked against PX4 at run time by px4_limits).
    "max_relative_altitude_m": FieldSpec("m", _OWNER),
    "min_waypoint_altitude_m": FieldSpec("m", _OWNER),
    "max_distance_from_home_m": FieldSpec("m", _OWNER),
    "max_speed_m_s": FieldSpec("m/s", _OWNER),
    "max_waypoints": FieldSpec("items", _OWNER, integer=True),
    # Preflight gate.
    "min_battery_fraction": FieldSpec("fraction 0-1", _OWNER),
    # One telemetry silence limit for preflight, mission and return watch;
    # set from the stream gaps seen over the real telemetry link.
    "max_telemetry_age_s": FieldSpec("s", _LINK),
    # Mission monitor.
    "start_timeout_s": FieldSpec("s", _TIMING),
    "max_item_time_s": FieldSpec("s", _TIMING),
    "max_mission_time_s": FieldSpec("s", _TIMING),
    "completion_grace_s": FieldSpec("s", _TIMING),
    # Return watch.
    "accept_timeout_s": FieldSpec("s", _TIMING),
    "max_return_time_s": FieldSpec("s", _TIMING),
    "disarm_timeout_s": FieldSpec("s", _TIMING),
    # Endurance input: logged time from takeoff to reaching the landing battery
    # reserve with this airframe, pack and payload. Flight measurement only.
    "usable_flight_time_s": FieldSpec("s", _FLIGHT),
}


class ProfileNotReady(ValueError):
    """The profile cannot produce real-aircraft settings; ``reasons`` lists why."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class FlightSettings:
    """Validated settings for the existing flight-layer modules."""

    mission_limits: MultirotorMissionLimits
    preflight_limits: PreflightLimits
    monitor_settings_for: Callable[[int], MonitorSettings]
    return_settings: ReturnSettings


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _field_findings(name: str, item: object, spec: FieldSpec) -> list[str]:
    if not isinstance(item, ModelInput):
        return [f"{name}: not a ModelInput"]
    found: list[str] = []
    if item.value is None:
        found.append(f"{name}: no value yet ({spec.unit})")
    elif not _is_number(item.value):
        found.append(f"{name}: value {item.value!r} is not a finite number")
    elif spec.integer and not isinstance(item.value, int):
        found.append(f"{name}: value {item.value!r} must be an integer")
    allowed = ", ".join(sorted(s.value for s in spec.allowed_sources))
    if item.source is None:
        found.append(f"{name}: no source recorded (allowed: {allowed})")
    elif item.source not in spec.allowed_sources:
        found.append(f"{name}: source {item.source.value} not accepted (allowed: {allowed})")
    if not item.reference.strip():
        found.append(f"{name}: no reference (decision date, bench record or log name)")
    return found


def profile_findings(inputs: Mapping[str, object]) -> tuple[str, ...]:
    """Every reason the inputs cannot become real-aircraft settings (empty = ready)."""

    findings: list[str] = []
    for name in sorted(set(inputs) - set(PROFILE_FIELDS)):
        findings.append(f"{name}: unknown profile field")
    for name, spec in PROFILE_FIELDS.items():
        if name not in inputs:
            findings.append(f"{name}: missing")
        else:
            findings.extend(_field_findings(name, inputs[name], spec))
    if findings:
        return tuple(findings)

    v = {name: inputs[name].value for name in PROFILE_FIELDS}  # type: ignore[union-attr]
    try:
        _build(v, expected_item_count=1)
    except ValueError as exc:
        findings.append(f"inconsistent settings: {exc}")
    budget = v["max_mission_time_s"] + v["max_return_time_s"]
    if budget > v["usable_flight_time_s"]:
        findings.append(
            f"max_mission_time_s + max_return_time_s = {budget:g} s exceeds "
            f"usable_flight_time_s = {v['usable_flight_time_s']:g} s"
        )
    return tuple(findings)


def _build(v: Mapping[str, float], expected_item_count: int) -> FlightSettings:
    mission_limits = MultirotorMissionLimits(
        max_relative_altitude_m=float(v["max_relative_altitude_m"]),
        min_waypoint_altitude_m=float(v["min_waypoint_altitude_m"]),
        max_distance_from_home_m=float(v["max_distance_from_home_m"]),
        max_speed_m_s=float(v["max_speed_m_s"]),
        max_waypoints=int(v["max_waypoints"]),
    )
    mission_limits.validate()
    preflight = PreflightLimits(
        min_battery_fraction=float(v["min_battery_fraction"]),
        max_telemetry_age_s=float(v["max_telemetry_age_s"]),
    )
    preflight.validate()
    returns = ReturnSettings(
        accept_timeout_s=float(v["accept_timeout_s"]),
        max_return_time_s=float(v["max_return_time_s"]),
        disarm_timeout_s=float(v["disarm_timeout_s"]),
        max_telemetry_age_s=float(v["max_telemetry_age_s"]),
    )
    returns.validate()

    def monitor_settings_for(item_count: int) -> MonitorSettings:
        settings = MonitorSettings(
            expected_item_count=item_count,
            start_timeout_s=float(v["start_timeout_s"]),
            max_item_time_s=float(v["max_item_time_s"]),
            max_mission_time_s=float(v["max_mission_time_s"]),
            max_telemetry_age_s=float(v["max_telemetry_age_s"]),
            completion_grace_s=float(v["completion_grace_s"]),
        )
        settings.validate()
        return settings

    monitor_settings_for(expected_item_count)
    return FlightSettings(mission_limits, preflight, monitor_settings_for, returns)


def build_flight_settings(inputs: Mapping[str, object]) -> FlightSettings:
    """Return validated settings, or raise :class:`ProfileNotReady` with every reason."""

    findings = profile_findings(inputs)
    if findings:
        raise ProfileNotReady(findings)
    return _build({name: inputs[name].value for name in PROFILE_FIELDS}, 1)  # type: ignore[union-attr]
