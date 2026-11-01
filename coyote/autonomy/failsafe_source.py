"""Candidate ``failsafe_active`` source: PX4 HEARTBEAT ``system_status``.

The R6 delegation authority refuses every grant while ``failsafe_active`` is
unknown, and until now nothing supplied it, so no grant was possible even in
SITL. This module is a **candidate** source, chosen as an implementation step
(not an owner requirement) so that SITL revocation tests become possible. It
has not been observed against PX4.

Why HEARTBEAT ``system_status``
-------------------------------
PX4 reports its overall state in every HEARTBEAT as a MAVLink ``MAV_STATE``.
As we read PX4's HEARTBEAT stream source (to be confirmed for the PX4 build
used in SITL), an active failsafe is reported as ``MAV_STATE_CRITICAL`` and
flight termination as ``MAV_STATE_FLIGHT_TERMINATION``; a healthy vehicle is
``MAV_STATE_STANDBY`` (disarmed) or ``MAV_STATE_ACTIVE`` (armed). MAVSDK 3.x
does not expose this field in its telemetry plugin, but its ``mavlink_direct``
plugin delivers raw messages as JSON (``MavlinkMessage.fields_json``; names
checked against MAVSDK-Python 3.17.2 without a vehicle).

Conservative mapping (implementation choice)
--------------------------------------------
* ``STANDBY`` / ``ACTIVE`` -> ``False`` (no failsafe reported).
* ``CRITICAL`` / ``EMERGENCY`` / ``FLIGHT_TERMINATION`` -> ``True``.
* ``UNINIT`` / ``BOOT`` / ``CALIBRATING`` / ``POWEROFF``, any unrecognised
  value, a malformed message or an autopilot that is not PX4 -> ``None``
  (unknown), which the authority treats as unsafe.
* Only heartbeats from the configured autopilot (system and component id) are
  used. Heartbeats from the ground station, the Jetson itself, a camera or a
  gimbal are ignored, so they can neither raise nor clear the failsafe state.

This is a defence-in-depth input. PX4 failsafe actions that change mode
(RTL, LAND) already revoke through the flight-mode stream.

Timing
------
PX4 normally sends HEARTBEAT at about 1 Hz, so the tracker's default 1 s
failsafe age would flip to unknown between heartbeats. Use
:data:`HEARTBEAT_TRACKER_CONFIG` (2.5 s, tolerating one late heartbeat) with
this source. Link-loss detection does not depend on it: the five telemetry
streams still revoke after the authority's 1 s age limit. Both numbers are
MODEL INPUTS / development placeholders; the real heartbeat rate is unobserved.

Read-only: nothing here sends a MAVLink message or commands the vehicle.
Unit-tested only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from coyote.autonomy.telemetry import TelemetryTracker, TelemetryTrackerConfig

# MAVLink common.xml MAV_STATE values.
MAV_STATE = {
    "MAV_STATE_UNINIT": 0,
    "MAV_STATE_BOOT": 1,
    "MAV_STATE_CALIBRATING": 2,
    "MAV_STATE_STANDBY": 3,
    "MAV_STATE_ACTIVE": 4,
    "MAV_STATE_CRITICAL": 5,
    "MAV_STATE_EMERGENCY": 6,
    "MAV_STATE_POWEROFF": 7,
    "MAV_STATE_FLIGHT_TERMINATION": 8,
}
_HEALTHY = frozenset({3, 4})
_FAILSAFE = frozenset({5, 6, 8})

MAV_AUTOPILOT_PX4 = 12
HEARTBEAT_SOURCE_KEY = "failsafe_heartbeat"

# MODEL INPUT / PLACEHOLDER: one 1 Hz heartbeat plus margin; not measured.
HEARTBEAT_TRACKER_CONFIG = TelemetryTrackerConfig(max_failsafe_age_s=2.5)


@dataclass(frozen=True)
class HeartbeatSourceConfig:
    """MODEL INPUTS: the autopilot's MAVLink identity.

    Defaults match PX4's ``MAV_SYS_ID`` default (1) and the autopilot
    component (``MAV_COMP_ID_AUTOPILOT1`` = 1). Coyote's real ids must be
    read from its parameters before use.
    """

    autopilot_system_id: int = 1
    autopilot_component_id: int = 1

    def validate(self) -> None:
        for name in ("autopilot_system_id", "autopilot_component_id"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 255:
                raise ValueError(f"{name} must be an integer from 1 to 255")


def _enum_value(raw: object, table: Mapping[str, int]) -> int | None:
    """Accept a MAVLink enum as an int or as its name (JSON form is unobserved)."""

    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        return table.get(raw.strip().upper())
    return None


def failsafe_from_system_status(system_status: object) -> bool | None:
    """Map a HEARTBEAT ``system_status`` to failsafe True/False/None (unknown)."""

    value = _enum_value(system_status, MAV_STATE)
    if value in _FAILSAFE:
        return True
    if value in _HEALTHY:
        return False
    return None


def failsafe_from_heartbeat(
    message: Any, config: HeartbeatSourceConfig | None = None
) -> tuple[bool, bool | None]:
    """Interpret one MAVSDK ``MavlinkMessage``.

    Returns ``(relevant, failsafe)``. ``relevant`` is False for messages that
    must be ignored entirely (not a HEARTBEAT, or not from the configured
    autopilot). For a relevant message ``failsafe`` is True, False or ``None``
    when the content is malformed, from a non-PX4 autopilot or in a state that
    does not establish health.
    """

    cfg = config or HeartbeatSourceConfig()
    if getattr(message, "message_name", None) != "HEARTBEAT":
        return False, None
    if (
        getattr(message, "system_id", None) != cfg.autopilot_system_id
        or getattr(message, "component_id", None) != cfg.autopilot_component_id
    ):
        return False, None
    try:
        fields = json.loads(getattr(message, "fields_json", ""))
    except (TypeError, ValueError):
        return True, None
    if not isinstance(fields, dict):
        return True, None
    autopilot = _enum_value(fields.get("autopilot"), {"MAV_AUTOPILOT_PX4": MAV_AUTOPILOT_PX4})
    if autopilot != MAV_AUTOPILOT_PX4:
        return True, None
    return True, failsafe_from_system_status(fields.get("system_status"))


async def pump_failsafe_heartbeat(
    drone: Any,
    tracker: TelemetryTracker,
    clock: Callable[[], float],
    stream_errors: dict[Any, str],
    config: HeartbeatSourceConfig | None = None,
) -> None:
    """Feed ``tracker.update_failsafe`` from ``drone.mavlink_direct`` HEARTBEATs.

    Read-only subscription. If the stream ends or raises, the reason is stored
    under :data:`HEARTBEAT_SOURCE_KEY` in ``stream_errors`` and updates stop,
    so the tracker's failsafe age expires and the authority revokes.
    """

    cfg = config or HeartbeatSourceConfig()
    cfg.validate()
    try:
        async for message in drone.mavlink_direct.message("HEARTBEAT"):
            relevant, failsafe = failsafe_from_heartbeat(message, cfg)
            if relevant:
                tracker.update_failsafe(failsafe, clock())
        stream_errors[HEARTBEAT_SOURCE_KEY] = "stream ended"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # kept for the report; failsafe state then goes stale
        stream_errors[HEARTBEAT_SOURCE_KEY] = f"{type(exc).__name__}: {exc}"


def subscribe_failsafe_heartbeat(
    drone: Any,
    tracker: TelemetryTracker,
    clock: Callable[[], float],
    stream_errors: dict[Any, str],
    config: HeartbeatSourceConfig | None = None,
) -> asyncio.Task:
    """Start :func:`pump_failsafe_heartbeat` as a task. Caller cancels it."""

    return asyncio.create_task(
        pump_failsafe_heartbeat(drone, tracker, clock, stream_errors, config)
    )
