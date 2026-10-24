"""Deterministic monitor for a PX4 waypoint mission that is already running.

Once a verified mission has been started, the companion/ground script must
decide, from telemetry alone, whether the mission is still progressing, has
completed, or has ended for some other reason. This module makes that decision
deterministically so it can be unit-tested without MAVSDK, a simulator or an
aircraft.

Authority boundary
------------------
* The monitor **never commands the vehicle**. It only classifies telemetry.
* PX4 keeps stabilization, geofence, battery and link-loss failsafes, RTL and
  pilot override. When PX4 or the pilot takes the aircraft out of MISSION mode
  the monitor ends the attempt and recommends nothing: the companion yields.
* When the mission stops advancing (an item takes too long or the whole
  mission exceeds its time budget) while PX4 is still in MISSION mode, the
  monitor ends the attempt with a *recommended* ``RETURN_TO_LAUNCH`` request.
  Whether to send it is the caller's decision; PX4 still decides how to fly it.
* Telemetry that stops arriving ends the attempt with no recommendation:
  PX4's own link-loss failsafe owns the aircraft.

Aircraft-agnostic: all timing values come from :class:`MonitorSettings`, which
the caller fills with per-aircraft **model inputs** (see
``x500/flight/monitor_settings.py`` for the X500 SITL placeholders).

Telemetry conventions (MAVSDK-Python 3.x, to be confirmed in PX4 SITL):
``telemetry.flight_mode()`` names, ``telemetry.armed()``,
``telemetry.in_air()`` and ``mission.mission_progress()`` where ``current`` is
the index of the active item and equals ``total`` once the mission is done.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# PX4 flight-mode names as reported by MAVSDK ``telemetry.flight_mode()``.
PILOT_CONTROLLED_MODES = frozenset(
    {"MANUAL", "STABILIZED", "ALTCTL", "POSCTL", "ACRO", "RATTITUDE"}
)
AUTOPILOT_RECOVERY_MODES = frozenset({"RETURN_TO_LAUNCH", "LAND"})
MISSION_MODE = "MISSION"
# Modes accepted at the moment the final item is reached. PX4 normally keeps
# AUTO_MISSION and loiters at the last item; HOLD is tolerated in case PX4/MAVSDK
# reports the post-mission loiter that way (to be confirmed in SITL).
COMPLETION_MODES = frozenset({MISSION_MODE, "HOLD"})


class MissionState(Enum):
    WAITING_FOR_START = "waiting_for_start"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ENDED = "ended"


class EndReason(Enum):
    START_TIMEOUT = "start_timeout"
    PILOT_TAKEOVER = "pilot_takeover"
    PX4_RECOVERY_MODE = "px4_recovery_mode"
    MODE_CHANGED = "mode_changed"
    DISARMED = "disarmed"
    LANDED_EARLY = "landed_early"
    NEVER_AIRBORNE = "never_airborne"
    MISSION_CHANGED = "mission_changed"
    PROGRESS_REGRESSED = "progress_regressed"
    ITEM_STALLED = "item_stalled"
    MISSION_TIMEOUT = "mission_timeout"
    TELEMETRY_STALE = "telemetry_stale"


class Recommendation(Enum):
    NONE = "none"
    RETURN_TO_LAUNCH = "return_to_launch"


# Reasons where the companion may *propose* RTL because PX4 is still flying the
# mission it was given but the mission is not finishing.
_RTL_RECOMMENDED = frozenset({EndReason.ITEM_STALLED, EndReason.MISSION_TIMEOUT})


@dataclass(frozen=True)
class MonitorSettings:
    """Per-aircraft timing budget. Every field is a model input, not a measurement."""

    expected_item_count: int
    start_timeout_s: float
    max_item_time_s: float
    max_mission_time_s: float
    max_telemetry_age_s: float

    def validate(self) -> None:
        if isinstance(self.expected_item_count, bool) or not isinstance(
            self.expected_item_count, int
        ):
            raise ValueError("expected_item_count must be an integer")
        if self.expected_item_count < 1:
            raise ValueError("expected_item_count must be at least 1")
        for name in (
            "start_timeout_s",
            "max_item_time_s",
            "max_mission_time_s",
            "max_telemetry_age_s",
        ):
            value = getattr(self, name)
            if not _is_finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.max_item_time_s > self.max_mission_time_s:
            raise ValueError("max_item_time_s must not exceed max_mission_time_s")


@dataclass(frozen=True)
class MissionSample:
    """One combined telemetry observation taken at ``time_s`` (monotonic seconds)."""

    time_s: float
    flight_mode: object
    armed: object
    in_air: object
    current_item: object
    total_items: object


@dataclass(frozen=True)
class MissionStatus:
    state: MissionState
    reason: EndReason | None = None
    recommendation: Recommendation = Recommendation.NONE
    current_item: int | None = None
    total_items: int | None = None
    detail: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.state in (MissionState.COMPLETED, MissionState.ENDED)


def normalize_flight_mode(mode: object) -> str:
    """Return an upper-case PX4 mode name from a MAVSDK enum member or a string."""

    name = getattr(mode, "name", mode)
    if isinstance(name, str) and name.strip():
        return name.strip().upper()
    return "UNKNOWN"


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class MissionExecutionMonitor:
    """Classify a running mission from telemetry samples.

    Call :meth:`start` immediately after the caller's ``mission.start_mission()``
    request is acknowledged, then feed every telemetry sample to :meth:`update`
    and call :meth:`check` periodically so silence is detected even when no
    samples arrive. Terminal results (``COMPLETED``/``ENDED``) are sticky.
    """

    def __init__(self, settings: MonitorSettings) -> None:
        settings.validate()
        self._settings = settings
        self._status = MissionStatus(MissionState.WAITING_FOR_START, detail="not started")
        self._started_at: float | None = None
        self._mission_mode_at: float | None = None
        self._last_valid_at: float | None = None
        self._last_sample_at: float | None = None
        self._item: int | None = None
        self._item_since: float | None = None
        self._was_airborne = False

    @property
    def status(self) -> MissionStatus:
        return self._status

    def start(self, now_s: float) -> MissionStatus:
        if not _is_finite_number(now_s):
            raise ValueError("start time must be finite")
        if self._started_at is not None:
            raise RuntimeError("monitor already started; create a new one per attempt")
        self._started_at = now_s
        self._last_valid_at = now_s
        self._status = MissionStatus(MissionState.WAITING_FOR_START, detail="start requested")
        return self._status

    def update(self, sample: MissionSample) -> MissionStatus:
        if self._started_at is None:
            raise RuntimeError("call start() before update()")
        if not _is_finite_number(sample.time_s):
            raise ValueError("sample time must be finite")
        if self._status.is_terminal:
            return self._status
        if self._last_sample_at is not None and sample.time_s < self._last_sample_at:
            # Out-of-order sample: ignore it; staleness keeps being measured.
            return self._status
        self._last_sample_at = sample.time_s

        if not self._sample_is_valid(sample):
            # Malformed telemetry does not refresh freshness; check() will end
            # the attempt as TELEMETRY_STALE if nothing valid follows.
            return self.check(sample.time_s)

        now = sample.time_s
        self._last_valid_at = now
        mode = normalize_flight_mode(sample.flight_mode)
        current = sample.current_item
        total = sample.total_items
        expected = self._settings.expected_item_count

        if mode in PILOT_CONTROLLED_MODES:
            return self._end(EndReason.PILOT_TAKEOVER, f"pilot mode {mode}", current, total)
        if mode in AUTOPILOT_RECOVERY_MODES:
            return self._end(EndReason.PX4_RECOVERY_MODE, f"PX4 mode {mode}", current, total)

        if self._status.state is MissionState.WAITING_FOR_START:
            if mode != MISSION_MODE:
                return self.check(now)
            if not sample.armed:
                # Mission mode on a disarmed vehicle has not started flying.
                return self.check(now)
            self._mission_mode_at = now
            self._item = None

        # From here PX4 has reported MISSION mode while armed at least once.
        if total != expected:
            return self._end(
                EndReason.MISSION_CHANGED,
                f"PX4 reports {total} items, expected {expected}",
                current,
                total,
            )
        if current > total:
            return self._end(
                EndReason.MISSION_CHANGED, f"item {current} beyond total {total}", current, total
            )
        if not sample.armed:
            return self._end(EndReason.DISARMED, "vehicle disarmed", current, total)
        if sample.in_air:
            self._was_airborne = True

        if self._item is not None and current < self._item:
            return self._end(
                EndReason.PROGRESS_REGRESSED,
                f"item went from {self._item} to {current}",
                current,
                total,
            )

        if current == total and mode in COMPLETION_MODES:
            if not self._was_airborne:
                return self._end(
                    EndReason.NEVER_AIRBORNE,
                    "final item reported without observed airborne state",
                    current,
                    total,
                )
            self._status = MissionStatus(
                MissionState.COMPLETED,
                current_item=current,
                total_items=total,
                detail=f"reached item {current}/{total}",
            )
            return self._status

        if mode != MISSION_MODE:
            return self._end(
                EndReason.MODE_CHANGED, f"mode {mode} before completion", current, total
            )
        if self._was_airborne and not sample.in_air:
            return self._end(EndReason.LANDED_EARLY, "landed before completion", current, total)

        if self._item is None or current != self._item:
            self._item = current
            self._item_since = now

        self._status = MissionStatus(
            MissionState.IN_PROGRESS,
            current_item=current,
            total_items=total,
            detail=f"item {current}/{total}",
        )
        return self.check(now)

    def check(self, now_s: float) -> MissionStatus:
        """Apply time-based rules at ``now_s`` without a new telemetry sample."""

        if self._started_at is None:
            raise RuntimeError("call start() before check()")
        if not _is_finite_number(now_s):
            raise ValueError("check time must be finite")
        if self._status.is_terminal:
            return self._status
        s = self._settings
        current, total = self._status.current_item, self._status.total_items

        if self._last_valid_at is not None and now_s - self._last_valid_at > s.max_telemetry_age_s:
            return self._end(
                EndReason.TELEMETRY_STALE,
                f"no valid telemetry for {now_s - self._last_valid_at:.1f} s",
                current,
                total,
            )
        if self._status.state is MissionState.WAITING_FOR_START:
            if now_s - self._started_at > s.start_timeout_s:
                return self._end(
                    EndReason.START_TIMEOUT, "PX4 did not report armed MISSION mode", None, None
                )
            return self._status
        if (
            self._mission_mode_at is not None
            and now_s - self._mission_mode_at > s.max_mission_time_s
        ):
            return self._end(
                EndReason.MISSION_TIMEOUT, "mission time budget exceeded", current, total
            )
        if self._item_since is not None and now_s - self._item_since > s.max_item_time_s:
            return self._end(
                EndReason.ITEM_STALLED,
                f"item {self._item} exceeded its time budget",
                current,
                total,
            )
        return self._status

    def _sample_is_valid(self, sample: MissionSample) -> bool:
        return (
            isinstance(sample.armed, bool)
            and isinstance(sample.in_air, bool)
            and _is_index(sample.current_item)
            and _is_index(sample.total_items)
            and normalize_flight_mode(sample.flight_mode) != "UNKNOWN"
        )

    def _end(
        self, reason: EndReason, detail: str, current: int | None, total: int | None
    ) -> MissionStatus:
        recommendation = (
            Recommendation.RETURN_TO_LAUNCH if reason in _RTL_RECOMMENDED else Recommendation.NONE
        )
        self._status = MissionStatus(
            MissionState.ENDED,
            reason=reason,
            recommendation=recommendation,
            current_item=current,
            total_items=total,
            detail=detail,
        )
        return self._status
