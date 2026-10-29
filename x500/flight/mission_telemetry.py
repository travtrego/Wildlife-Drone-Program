"""Feed PX4 telemetry streams into the mission execution monitor.

:mod:`x500.flight.mission_monitor` classifies a running mission from combined
:class:`MissionSample` observations, but MAVSDK delivers flight mode, armed,
in-air and mission progress as four independent async streams. This module is
the missing link:

* :class:`MissionTelemetryCombiner` (no MAVSDK, no asyncio) keeps the latest
  value of each stream and builds one sample whose timestamp honestly reflects
  the *oldest* periodic stream, so one silent stream makes the monitor see
  stale telemetry even while the others keep arriving.
* :func:`subscribe_mission_telemetry` runs one task per MAVSDK stream that
  only *reads* telemetry into the combiner.
* :func:`run_monitor` drives the monitor on a fixed check interval until it
  reaches a terminal result.
* :func:`follow_up_request` decides, after the monitor ends, whether the
  ground script may *request* ``RETURN_TO_LAUNCH`` from PX4, re-checking fresh
  telemetry so it never overrides a pilot or a PX4 recovery mode.

Authority boundary
------------------
Nothing here arms, starts a mission or sends a flight command. PX4 keeps
stabilization, geofence, battery and link-loss failsafes, RTL and pilot
override. The only output that can lead to a command is a *request* from
:func:`follow_up_request`, which the caller may send; PX4 decides how to fly it.

Conservative rules (implementation choices, not owner requirements)
-------------------------------------------------------------------
* **Freshness comes from periodic streams only.** Flight mode, armed and in-air
  are assumed to be re-sent periodically (heartbeat / extended system state).
  Mission progress may be reported only when it changes, so it is latched and
  required once but does not set the sample age. Both assumptions are
  **unconfirmed in PX4 SITL**.
* **No sample until every stream has reported once.** The monitor then times
  out (``START_TIMEOUT`` or ``TELEMETRY_STALE``) rather than guessing.
* **Pre-start telemetry is not fed.** Samples whose periodic streams are all
  older than the mission start request are ignored, so the vehicle state before
  ``start_mission`` cannot be mistaken for the mission's state.
* **Out-of-order updates are dropped** per stream.
* **A stream that ends or fails stops updating**; the monitor then reports
  ``TELEMETRY_STALE``. The error is kept for the report, not swallowed.

Aircraft-agnostic: every timing value comes from the caller (X500 SITL
placeholders live in ``monitor_settings.py``). Unit-tested only.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .mission_monitor import (
    AUTOPILOT_RECOVERY_MODES,
    COMPLETION_MODES,
    PILOT_CONTROLLED_MODES,
    MissionExecutionMonitor,
    MissionSample,
    MissionState,
    MissionStatus,
    Recommendation,
    normalize_flight_mode,
)


class MissionStream(Enum):
    FLIGHT_MODE = "flight_mode"
    ARMED = "armed"
    IN_AIR = "in_air"
    PROGRESS = "mission_progress"


# Streams whose update times set the sample age (see module docstring).
PERIODIC_STREAMS = (MissionStream.FLIGHT_MODE, MissionStream.ARMED, MissionStream.IN_AIR)


def _require_time(now_s: float) -> None:
    if isinstance(now_s, bool) or not isinstance(now_s, int | float) or not math.isfinite(now_s):
        raise ValueError("telemetry timestamp must be a finite monotonic time")


class MissionTelemetryCombiner:
    """Latest value and receive time of each mission telemetry stream.

    Values are stored as received; :class:`MissionExecutionMonitor` decides
    whether a sample is valid, so malformed telemetry never refreshes it.
    """

    def __init__(self) -> None:
        self._values: dict[MissionStream, Any] = {}
        self._times: dict[MissionStream, float] = {}
        self.stream_errors: dict[MissionStream, str] = {}

    def update_flight_mode(self, mode: object, now_s: float) -> None:
        self._set(MissionStream.FLIGHT_MODE, mode, now_s)

    def update_armed(self, armed: object, now_s: float) -> None:
        self._set(MissionStream.ARMED, armed, now_s)

    def update_in_air(self, in_air: object, now_s: float) -> None:
        self._set(MissionStream.IN_AIR, in_air, now_s)

    def update_progress(self, current: object, total: object, now_s: float) -> None:
        self._set(MissionStream.PROGRESS, (current, total), now_s)

    def record_stream_end(self, stream: MissionStream, detail: str) -> None:
        self.stream_errors[stream] = detail

    def missing_streams(self) -> tuple[MissionStream, ...]:
        return tuple(s for s in MissionStream if s not in self._values)

    def sample(self) -> MissionSample | None:
        """Combined sample stamped with the oldest periodic update, or None."""

        if self.missing_streams():
            return None
        current, total = self._values[MissionStream.PROGRESS]
        return MissionSample(
            time_s=min(self._times[s] for s in PERIODIC_STREAMS),
            flight_mode=self._values[MissionStream.FLIGHT_MODE],
            armed=self._values[MissionStream.ARMED],
            in_air=self._values[MissionStream.IN_AIR],
            current_item=current,
            total_items=total,
        )

    def _set(self, stream: MissionStream, value: object, now_s: float) -> None:
        _require_time(now_s)
        last = self._times.get(stream)
        if last is not None and now_s < last:
            return  # out-of-order delivery; keep the newer value
        self._values[stream] = value
        self._times[stream] = now_s


async def _pump(
    stream: MissionStream,
    source: Callable[[], Any],
    handle: Callable[[Any, float], None],
    combiner: MissionTelemetryCombiner,
    clock: Callable[[], float],
) -> None:
    try:
        async for value in source():
            handle(value, clock())
        combiner.record_stream_end(stream, "stream ended")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # kept for the report; the monitor then goes stale
        combiner.record_stream_end(stream, f"{type(exc).__name__}: {exc}")


def subscribe_mission_telemetry(
    drone: Any,
    combiner: MissionTelemetryCombiner,
    clock: Callable[[], float],
) -> list[asyncio.Task]:
    """Start one read-only task per MAVSDK stream. Caller cancels them.

    ``drone`` needs ``telemetry.flight_mode/armed/in_air`` and
    ``mission.mission_progress`` async-generator methods (MAVSDK ``System``).
    """

    c = combiner
    specs = (
        (MissionStream.FLIGHT_MODE, drone.telemetry.flight_mode, c.update_flight_mode),
        (MissionStream.ARMED, drone.telemetry.armed, c.update_armed),
        (MissionStream.IN_AIR, drone.telemetry.in_air, c.update_in_air),
        (
            MissionStream.PROGRESS,
            drone.mission.mission_progress,
            lambda p, t: c.update_progress(
                getattr(p, "current", None), getattr(p, "total", None), t
            ),
        ),
    )
    return [
        asyncio.create_task(_pump(stream, source, handle, combiner, clock))
        for stream, source, handle in specs
    ]


async def run_monitor(
    monitor: MissionExecutionMonitor,
    combiner: MissionTelemetryCombiner,
    started_at_s: float,
    clock: Callable[[], float],
    check_interval_s: float,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> MissionStatus:
    """Feed new samples and periodic checks until the monitor is terminal.

    ``monitor.start(started_at_s)`` must already have been called. Termination
    is guaranteed as long as ``clock`` advances: the monitor's start, item,
    mission and telemetry-age budgets all end the attempt.
    """

    _require_time(started_at_s)
    if not math.isfinite(check_interval_s) or check_interval_s <= 0.0:
        raise ValueError("check_interval_s must be a positive finite number")
    last_fed: MissionSample | None = None
    while True:
        sample = combiner.sample()
        if sample is not None and sample.time_s >= started_at_s and sample != last_fed:
            monitor.update(sample)
            last_fed = sample
        status = monitor.check(clock())
        if status.is_terminal:
            return status
        await sleep(check_interval_s)


@dataclass(frozen=True)
class FollowUp:
    """What the ground script may request after the monitor ends."""

    request_return_to_launch: bool
    reason: str


def follow_up_request(
    status: MissionStatus,
    latest: MissionSample | None,
    now_s: float,
    max_telemetry_age_s: float,
) -> FollowUp:
    """Decide whether to *request* RTL after a terminal monitor result.

    RTL is requested only when the mission completed (it ends hovering at the
    last item) or the monitor recommended RTL, **and** fresh, valid telemetry
    still shows armed, airborne and PX4 in an autonomous mission/hold mode.
    Pilot modes, PX4 RTL/LAND, stale or invalid telemetry and every other end
    reason get no request: the pilot or PX4 already owns the aircraft.
    """

    _require_time(now_s)
    if not status.is_terminal:
        return FollowUp(False, "monitor has not finished")
    wanted = status.state is MissionState.COMPLETED or (
        status.recommendation is Recommendation.RETURN_TO_LAUNCH
    )
    if not wanted:
        reason = status.reason.value if status.reason else status.state.value
        return FollowUp(False, f"no follow-up for {reason}; PX4/pilot owns the aircraft")
    if latest is None or not math.isfinite(max_telemetry_age_s):
        return FollowUp(False, "no telemetry to confirm vehicle state")
    age = now_s - latest.time_s
    if age < 0.0 or age > max_telemetry_age_s:
        return FollowUp(False, f"telemetry is {age:.1f} s old")
    mode = normalize_flight_mode(latest.flight_mode)
    if mode in PILOT_CONTROLLED_MODES:
        return FollowUp(False, f"pilot mode {mode}")
    if mode in AUTOPILOT_RECOVERY_MODES:
        return FollowUp(False, f"PX4 already in {mode}")
    if mode not in COMPLETION_MODES:
        return FollowUp(False, f"mode {mode} is not MISSION/HOLD")
    if latest.armed is not True or latest.in_air is not True:
        return FollowUp(False, "vehicle not armed and airborne")
    return FollowUp(True, f"{status.state.value}: request PX4 RETURN_TO_LAUNCH")
