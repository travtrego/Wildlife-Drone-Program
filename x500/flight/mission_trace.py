"""Read-only observation trace of a monitored waypoint mission.

The 2026-11-01 SITL records could not say which flight modes PX4 reported
during takeoff and after the last item, what ``mission_progress`` reported at
start, how long each item took or how often each stream arrived, because the
flight script printed only the final monitor result. The final-HOLD race found
that afternoon was diagnosed from PX4's own console, not from the script. The
monitor's timing values (start, per-item, mission and telemetry-age budgets)
are therefore still unmeasured placeholders.

:class:`MissionTrace` records what the companion actually received so the next
SITL session can measure them:

* a timestamped **event** whenever a stream's value changes (flight mode,
  armed, in-air, mission progress) or the monitor state changes, with times
  relative to the ``start_mission`` request (negative = before it);
* per-stream **counts, mean rate and largest gap** between updates;
* **per-item durations** from ``mission_progress`` changes;
* a **comparison against the monitor settings in use**, so a reviewer can see
  how much margin each placeholder had in that run.

Authority boundary: the trace only observes. It never commands the vehicle,
never changes what the monitor sees and never decides pass/fail. Its numbers
are observations of one run (simulator or otherwise) and are not validated
envelopes; changing a placeholder from them is a separate, reviewed decision.

Aircraft-agnostic (no X500 numbers here). Unit-tested only.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .mission_monitor import MissionStatus, MonitorSettings, normalize_flight_mode
from .mission_telemetry import PERIODIC_STREAMS, MissionStream


@dataclass(frozen=True)
class TraceEvent:
    time_s: float  # monotonic receive time
    source: str  # stream name or "monitor"
    text: str


@dataclass
class _StreamStats:
    count: int = 0
    first_s: float | None = None
    last_s: float | None = None
    max_gap_s: float = 0.0
    # Largest gap as the monitor sees it: time since max(previous update, start).
    max_gap_since_start_s: float | None = None
    last_text: str | None = None


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _describe(stream: MissionStream, value: object) -> str:
    if stream is MissionStream.FLIGHT_MODE:
        return normalize_flight_mode(value)
    if stream is MissionStream.PROGRESS and isinstance(value, tuple) and len(value) == 2:
        return f"{value[0]!r}/{value[1]!r}"
    return repr(value)


def _status_text(status: MissionStatus) -> str:
    parts = [status.state.value]
    if status.reason is not None:
        parts.append(status.reason.value)
    if status.detail:
        parts.append(status.detail)
    if "item" not in status.detail and (
        status.current_item is not None or status.total_items is not None
    ):
        parts.append(f"(item {status.current_item}/{status.total_items})")
    return " ".join(parts)


class MissionTrace:
    """Record mission telemetry as received; summarize it after the run.

    ``emit`` (e.g. ``print``) receives one line per event as it happens so a
    terminal transcript keeps the order of events even if the run aborts.
    """

    def __init__(self, emit: Callable[[str], None] | None = None) -> None:
        self._emit = emit
        self._stats: dict[MissionStream, _StreamStats] = {s: _StreamStats() for s in MissionStream}
        self._events: list[TraceEvent] = []
        self._start_s: float | None = None
        self._last_monitor_text: str | None = None
        # (receive time, current index) for every change of progress.current
        self._progress_changes: list[tuple[float, object, object]] = []

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    @property
    def start_s(self) -> float | None:
        return self._start_s

    def mark_start(self, now_s: float) -> None:
        """Record the ``start_mission`` request time; event times are relative to it."""

        if not _finite(now_s):
            raise ValueError("start time must be finite")
        if self._start_s is not None:
            raise RuntimeError("trace start already marked; use one trace per attempt")
        self._start_s = now_s
        self._add(now_s, "script", "start_mission requested")

    def observe(self, stream: MissionStream, value: object, now_s: float) -> None:
        """Record one accepted stream update (``MissionTelemetryCombiner`` observer)."""

        if not _finite(now_s):
            return  # the combiner rejects these too; never let the trace raise mid-flight
        stats = self._stats[stream]
        if stats.last_s is not None:
            stats.max_gap_s = max(stats.max_gap_s, now_s - stats.last_s)
        if self._start_s is not None and now_s >= self._start_s:
            since = now_s - max(stats.last_s if stats.last_s is not None else now_s, self._start_s)
            stats.max_gap_since_start_s = max(stats.max_gap_since_start_s or 0.0, since)
        if stats.first_s is None:
            stats.first_s = now_s
        stats.last_s = now_s
        stats.count += 1
        text = _describe(stream, value)
        if text != stats.last_text:
            stats.last_text = text
            self._add(now_s, stream.value, text)
            if stream is MissionStream.PROGRESS and isinstance(value, tuple) and len(value) == 2:
                previous = self._progress_changes[-1][1] if self._progress_changes else None
                if value[0] != previous:
                    self._progress_changes.append((now_s, value[0], value[1]))

    def monitor_status(self, status: MissionStatus, now_s: float) -> None:
        """Record a monitor state change (``run_monitor`` observer)."""

        text = _status_text(status)
        if text != self._last_monitor_text and _finite(now_s):
            self._last_monitor_text = text
            self._add(now_s, "monitor", text)

    # --- derived observations -------------------------------------------------

    def first_event_after_start(self, source: str, text: str) -> float | None:
        """Seconds from the start request to the first matching event, or None."""

        if self._start_s is None:
            return None
        for event in self._events:
            if event.time_s >= self._start_s and event.source == source and event.text == text:
                return event.time_s - self._start_s
        return None

    def item_durations(self) -> list[tuple[object, float]]:
        """``(item index, seconds it was the current item)`` after the start request.

        The item that was current when the start request was sent (last value
        reported before it) is timed from the request, so takeoff counts toward
        it. Only items whose end was observed (a later progress change) are
        listed.
        """

        if self._start_s is None:
            return []
        start = self._start_s
        before = [c for c in self._progress_changes if c[0] < start]
        changes = [c for c in self._progress_changes if c[0] >= start]
        if before and (not changes or changes[0][0] > start):
            changes.insert(0, (start, before[-1][1], before[-1][2]))
        return [(a[1], b[0] - a[0]) for a, b in zip(changes, changes[1:], strict=False)]

    def mission_duration_s(self) -> float | None:
        """Start request to the first progress report with ``current == total``."""

        if self._start_s is None:
            return None
        for time_s, current, total in self._progress_changes:
            if time_s >= self._start_s and current == total:
                return time_s - self._start_s
        return None

    def stream_stats(self, stream: MissionStream) -> tuple[int, float | None, float | None]:
        """``(count, mean rate Hz or None, largest gap s or None)`` for one stream."""

        s = self._stats[stream]
        if s.count < 2 or s.first_s is None or s.last_s is None or s.last_s <= s.first_s:
            return s.count, None, None
        return s.count, (s.count - 1) / (s.last_s - s.first_s), s.max_gap_s

    def summary_lines(self, settings: MonitorSettings | None = None) -> list[str]:
        """Human-readable observations, and margins against ``settings`` if given."""

        lines = ["Mission trace (observations from this run only; not validated limits):"]
        lines.append("  stream             count   mean rate   largest gap")
        for stream in MissionStream:
            count, rate, gap = self.stream_stats(stream)
            rate_text = f"{rate:7.2f} Hz" if rate is not None else "      n/a"
            gap_text = f"{gap:7.2f} s" if gap is not None else "      n/a"
            lines.append(f"  {stream.value:17s} {count:6d}  {rate_text}  {gap_text}")

        start_mode = self.first_event_after_start(MissionStream.FLIGHT_MODE.value, "MISSION")
        airborne = self.first_event_after_start(MissionStream.IN_AIR.value, "True")
        durations = self.item_durations()
        mission = self.mission_duration_s()
        lines.append(f"  MISSION mode first reported: {_seconds(start_mode)} after start request")
        lines.append(f"  in_air True first reported:  {_seconds(airborne)} after start request")
        if durations:
            shown = ", ".join(f"{item}: {d:.2f}s" for item, d in durations)
            lines.append(f"  item durations: {shown}")
        else:
            lines.append("  item durations: none observed")
        lines.append(f"  final item reached:          {_seconds(mission)} after start request")

        if settings is not None:
            longest_item = max((d for _, d in durations), default=None)
            # As the monitor sees it: only after the start request, and the
            # oldest periodic stream sets the sample age.
            known_gaps = [
                g
                for g in (self._stats[s].max_gap_since_start_s for s in PERIODIC_STREAMS)
                if g is not None
            ]
            largest_gap = max(known_gaps) if known_gaps else None
            lines.append("  vs monitor settings in use (model inputs / placeholders):")
            for label, observed, limit in (
                ("start (MISSION mode)", start_mode, settings.start_timeout_s),
                ("longest item", longest_item, settings.max_item_time_s),
                ("whole mission", mission, settings.max_mission_time_s),
                ("periodic gap (run)", largest_gap, settings.max_telemetry_age_s),
            ):
                lines.append(f"    {label:21s} {_margin(observed, limit)}")
        return lines

    def _add(self, now_s: float, source: str, text: str) -> None:
        self._events.append(TraceEvent(now_s, source, text))
        if self._emit is not None:
            self._emit(f"[{self._relative(now_s)}] {source}: {text}")

    def _relative(self, now_s: float) -> str:
        if self._start_s is None:
            return "  pre-start"
        return f"{now_s - self._start_s:+9.2f}s"


def _seconds(value: float | None) -> str:
    return f"{value:.2f} s" if value is not None else "not observed"


def _margin(observed: float | None, limit: float) -> str:
    if observed is None:
        return f"not observed (placeholder {limit:g} s)"
    flag = "  EXCEEDS PLACEHOLDER" if observed > limit else ""
    return f"{observed:.2f} s of {limit:g} s ({observed / limit:.0%}){flag}"
