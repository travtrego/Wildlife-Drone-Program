"""Deterministic watch of a PX4 return-to-launch after the companion requested it.

``waypoint_mission_flight`` requests PX4 ``RETURN_TO_LAUNCH`` after a completed
(or stalled) mission. Until now it then only waited for ``in_air`` to become
False. That could not tell a normal PX4 return and landing apart from PX4
ignoring the request, a pilot taking over, PX4 leaving RTL for another mode, a
vehicle that landed but never disarmed, or telemetry that stopped. This module
classifies those cases from telemetry alone so they can be unit-tested and
reported.

Authority boundary
------------------
* The monitor **never commands the vehicle and never recommends a command**.
  Once RTL has been requested PX4 owns the aircraft: it flies the return,
  lands and disarms; the pilot can take over at any time. Every non-nominal
  outcome ends the watch and the script sends nothing further.
* It does not retry the RTL request, does not request LAND or disarm, and does
  not treat its own timeouts as a reason to act.

Classification (implementation choices, not owner requirements)
---------------------------------------------------------------
* ``LANDED`` (pass): PX4 reported ``RETURN_TO_LAUNCH`` or ``LAND`` at least
  once after the request, then ``in_air`` False, then disarmed.
* Before PX4 reports a recovery mode, the pre-request modes ``MISSION``/``HOLD``
  are tolerated for ``accept_timeout_s``; any other mode ends the watch.
* After a recovery mode, any mode other than ``RETURN_TO_LAUNCH``/``LAND`` while
  airborne ends the watch as ``MODE_CHANGED`` (PX4 or someone else changed it).
* A pilot mode ends the watch as ``PILOT_TAKEOVER`` in every state.
* On the ground the mode is ignored (PX4's post-landing mode is unobserved). If
  ``in_air`` returns True before disarm, the watch goes back to returning
  (land-detector bounce) and the overall time budget keeps running.
* Malformed samples do not refresh freshness; silence for longer than
  ``max_telemetry_age_s`` ends the watch as ``TELEMETRY_STALE`` (PX4's link-loss
  failsafe owns the aircraft).

Aircraft-agnostic: every timing value comes from :class:`ReturnSettings`, filled
with per-aircraft **model inputs** (X500 SITL placeholders live in
``monitor_settings.py``). Unit-tested only; not yet run in PX4 SITL.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .mission_monitor import (
    AUTOPILOT_RECOVERY_MODES,
    COMPLETION_MODES,
    PILOT_CONTROLLED_MODES,
    MissionSample,
    normalize_flight_mode,
)


class ReturnState(Enum):
    WAITING_FOR_RETURN = "waiting_for_return"  # request sent, PX4 not yet in RTL/LAND
    RETURNING = "returning"  # PX4 in RTL/LAND, airborne
    LANDED_ARMED = "landed_armed"  # on the ground, waiting for PX4 to disarm
    LANDED = "landed"  # terminal success: on the ground and disarmed
    ENDED = "ended"  # terminal, any other outcome


class ReturnEndReason(Enum):
    RETURN_NOT_ACCEPTED = "return_not_accepted"
    PILOT_TAKEOVER = "pilot_takeover"
    MODE_CHANGED = "mode_changed"
    DISARMED_IN_AIR = "disarmed_in_air"
    LANDED_WITHOUT_RETURN = "landed_without_return"
    LANDED_NOT_DISARMED = "landed_not_disarmed"
    RETURN_TIMEOUT = "return_timeout"
    TELEMETRY_STALE = "telemetry_stale"


@dataclass(frozen=True)
class ReturnSettings:
    """Per-aircraft budget for the return watch. Every field is a model input."""

    accept_timeout_s: float  # request -> PX4 reports RETURN_TO_LAUNCH/LAND
    max_return_time_s: float  # request -> landed and disarmed
    disarm_timeout_s: float  # landed -> disarmed
    max_telemetry_age_s: float

    def validate(self) -> None:
        for name in (
            "accept_timeout_s",
            "max_return_time_s",
            "disarm_timeout_s",
            "max_telemetry_age_s",
        ):
            value = getattr(self, name)
            if not _is_finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.accept_timeout_s > self.max_return_time_s:
            raise ValueError("accept_timeout_s must not exceed max_return_time_s")
        if self.disarm_timeout_s > self.max_return_time_s:
            raise ValueError("disarm_timeout_s must not exceed max_return_time_s")


@dataclass(frozen=True)
class ReturnStatus:
    state: ReturnState
    reason: ReturnEndReason | None = None
    detail: str = ""
    # Same shape as MissionStatus so MissionTrace.monitor_status can print it.
    current_item: int | None = None
    total_items: int | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in (ReturnState.LANDED, ReturnState.ENDED)

    @property
    def landed_and_disarmed(self) -> bool:
        return self.state is ReturnState.LANDED


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ReturnLandingMonitor:
    """Classify PX4's return and landing after an RTL request.

    Call :meth:`start` right after the ``return_to_launch`` request returns,
    feed only samples taken at or after that time to :meth:`update`, and call
    :meth:`check` periodically so silence and timeouts are detected. Terminal
    results are sticky; create a new monitor per request.
    """

    def __init__(self, settings: ReturnSettings) -> None:
        settings.validate()
        self._settings = settings
        self._status = ReturnStatus(ReturnState.WAITING_FOR_RETURN, detail="not started")
        self._requested_at: float | None = None
        self._last_valid_at: float | None = None
        self._last_sample_at: float | None = None
        self._landed_since: float | None = None

    @property
    def status(self) -> ReturnStatus:
        return self._status

    def start(self, now_s: float) -> ReturnStatus:
        if not _is_finite_number(now_s):
            raise ValueError("start time must be finite")
        if self._requested_at is not None:
            raise RuntimeError("monitor already started; create a new one per request")
        self._requested_at = now_s
        self._last_valid_at = now_s
        self._status = ReturnStatus(ReturnState.WAITING_FOR_RETURN, detail="RTL requested")
        return self._status

    def update(self, sample: MissionSample) -> ReturnStatus:
        if self._requested_at is None:
            raise RuntimeError("call start() before update()")
        if not _is_finite_number(sample.time_s):
            raise ValueError("sample time must be finite")
        if self._status.is_terminal:
            return self._status
        if sample.time_s < self._requested_at:
            return self._status  # pre-request state says nothing about the return
        if self._last_sample_at is not None and sample.time_s < self._last_sample_at:
            return self._status  # out of order
        self._last_sample_at = sample.time_s

        mode = normalize_flight_mode(sample.flight_mode)
        if not (
            isinstance(sample.armed, bool) and isinstance(sample.in_air, bool) and mode != "UNKNOWN"
        ):
            return self.check(sample.time_s)  # malformed: does not refresh freshness

        now = sample.time_s
        self._last_valid_at = now
        state = self._status.state

        if mode in PILOT_CONTROLLED_MODES:
            return self._end(ReturnEndReason.PILOT_TAKEOVER, f"pilot mode {mode}")

        if state is ReturnState.WAITING_FOR_RETURN:
            if not sample.in_air:
                return self._end(
                    ReturnEndReason.LANDED_WITHOUT_RETURN,
                    f"on the ground in {mode} before PX4 reported RTL/LAND",
                )
            if not sample.armed:
                return self._end(ReturnEndReason.DISARMED_IN_AIR, "disarmed while airborne")
            if mode in AUTOPILOT_RECOVERY_MODES:
                self._status = ReturnStatus(ReturnState.RETURNING, detail=f"PX4 {mode}")
                return self.check(now)
            if mode in COMPLETION_MODES:
                return self.check(now)  # PX4 has not switched yet; accept timeout runs
            return self._end(
                ReturnEndReason.MODE_CHANGED, f"mode {mode} before PX4 reported RTL/LAND"
            )

        # RETURNING or LANDED_ARMED: PX4 has reported a recovery mode.
        if sample.in_air:
            if not sample.armed:
                return self._end(ReturnEndReason.DISARMED_IN_AIR, "disarmed while airborne")
            if mode not in AUTOPILOT_RECOVERY_MODES:
                return self._end(ReturnEndReason.MODE_CHANGED, f"PX4 left RTL/LAND for {mode}")
            self._landed_since = None  # airborne again (or still): keep returning
            self._status = ReturnStatus(ReturnState.RETURNING, detail=f"PX4 {mode}")
            return self.check(now)

        if not sample.armed:
            self._status = ReturnStatus(ReturnState.LANDED, detail=f"landed and disarmed ({mode})")
            return self._status
        if self._landed_since is None:
            self._landed_since = now
        self._status = ReturnStatus(ReturnState.LANDED_ARMED, detail="landed; awaiting disarm")
        return self.check(now)

    def check(self, now_s: float) -> ReturnStatus:
        """Apply the time-based rules at ``now_s`` without a new sample."""

        if self._requested_at is None:
            raise RuntimeError("call start() before check()")
        if not _is_finite_number(now_s):
            raise ValueError("check time must be finite")
        if self._status.is_terminal:
            return self._status
        s = self._settings
        if now_s - self._last_valid_at > s.max_telemetry_age_s:
            return self._end(
                ReturnEndReason.TELEMETRY_STALE,
                f"no valid telemetry for {now_s - self._last_valid_at:.1f} s",
            )
        elapsed = now_s - self._requested_at
        if self._status.state is ReturnState.WAITING_FOR_RETURN and elapsed > s.accept_timeout_s:
            return self._end(
                ReturnEndReason.RETURN_NOT_ACCEPTED,
                f"PX4 did not report RTL/LAND within {s.accept_timeout_s:.1f} s",
            )
        if (
            self._status.state is ReturnState.LANDED_ARMED
            and self._landed_since is not None
            and now_s - self._landed_since > s.disarm_timeout_s
        ):
            return self._end(
                ReturnEndReason.LANDED_NOT_DISARMED,
                f"still armed {now_s - self._landed_since:.1f} s after landing",
            )
        if elapsed > s.max_return_time_s:
            return self._end(
                ReturnEndReason.RETURN_TIMEOUT,
                f"not landed and disarmed within {s.max_return_time_s:.1f} s",
            )
        return self._status

    def _end(self, reason: ReturnEndReason, detail: str) -> ReturnStatus:
        self._status = ReturnStatus(ReturnState.ENDED, reason=reason, detail=detail)
        return self._status
