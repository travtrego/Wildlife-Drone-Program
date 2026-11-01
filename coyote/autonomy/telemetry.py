"""Turn per-stream PX4 telemetry into the gate's :class:`VehicleSnapshot`.

MAVSDK delivers vehicle state as independent async streams (flight mode,
armed, in-air, position, battery). The action gate and delegation authority
need one :class:`~coyote.autonomy.action_gate.VehicleSnapshot` whose
``telemetry_age_s`` honestly reflects whether the link is alive and every
stream is fresh.
This module is that adapter, with no MAVSDK import so it stays unit-testable:
the future MAVSDK task only calls ``update_*`` with values it receives and a
monotonic timestamp.

Conservative rules (implementation choices, not new owner requirements)
----------------------------------------------------------------------
* **Each stream has its own staleness limit; the link age is the newest
  update.** PX4 SITL (2026-11-01, see ``docs/SITL_VALIDATION_2026-11-01.md``)
  sent flight mode, armed and in-air at 1 Hz, position at about 50 Hz and
  battery at about 0.6 Hz. Using the *oldest* stream as the age (the previous
  rule) made the snapshot look 1.4 s old on a healthy link and revoked every
  grant within a second. Now any required stream older than its own limit in
  ``TelemetryTrackerConfig.stream_max_age_s`` makes the snapshot report that
  stream's (stale) age, so the authority revokes; otherwise
  ``telemetry_age_s`` is the age of the *newest* update, which measures
  whether the link is alive. Every per-stream limit must be at least the
  authority's and gate's age limit (1 s placeholder).
* **Missing or invalid means unknown.** A required stream that was never
  received, or whose last value was malformed (non-bool armed/in-air,
  non-finite altitude), makes ``telemetry_age_s`` infinite, which the gate and
  delegation authority already reject.
* **Battery units are converted once, here.** MAVSDK 3.x reports
  ``Battery.remaining_percent`` on a 0-100 scale; the gate expects a 0.0-1.0
  fraction. Values outside 0-100 or non-finite become ``None`` (unknown), which
  the gate refuses for takeoff and goto.
* **Out-of-order updates are dropped.** An update older than the stream's last
  accepted update is ignored, so a delayed message cannot make state look
  fresher or roll it back.
* **Failsafe state is a separate input.** A candidate source (PX4 HEARTBEAT
  ``system_status``) is in ``failsafe_source.py``; it is unobserved. Until a
  source calls :meth:`TelemetryTracker.update_failsafe`, or when its value is
  older than ``max_failsafe_age_s``, :meth:`TelemetryTracker.failsafe_active`
  returns ``None`` and the delegation authority treats that as unsafe.

Nothing here commands the vehicle. Timing defaults are MODEL INPUTS /
development placeholders, not tested values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from coyote.autonomy.action_gate import (
    ActionRequest,
    AdvisoryLimits,
    GateDecision,
    VehicleSnapshot,
    evaluate_request,
)
from coyote.autonomy.delegation import DelegationAuthority


class Stream(Enum):
    FLIGHT_MODE = "flight_mode"
    ARMED = "armed"
    IN_AIR = "in_air"
    POSITION = "position"
    BATTERY = "battery"


REQUIRED_STREAMS = tuple(Stream)

UNKNOWN_MODE = "UNKNOWN"


def _default_stream_max_age_s() -> dict[Stream, float]:
    # MODEL INPUTS / PLACEHOLDERS, sized from one PX4 SITL observation on
    # 2026-11-01 (about two intervals of each observed rate). Not measured on
    # Coyote's real link.
    return {
        Stream.FLIGHT_MODE: 2.5,  # 1 Hz observed
        Stream.ARMED: 2.5,  # 1 Hz observed
        Stream.IN_AIR: 2.5,  # 1 Hz observed
        Stream.POSITION: 1.0,  # ~50 Hz observed
        Stream.BATTERY: 4.0,  # ~0.6 Hz observed
    }


@dataclass(frozen=True)
class TelemetryTrackerConfig:
    """MODEL INPUTS / PLACEHOLDERS: see ``_default_stream_max_age_s``."""

    max_failsafe_age_s: float = 1.0
    stream_max_age_s: dict[Stream, float] = field(default_factory=_default_stream_max_age_s)

    def validate(self) -> None:
        if not math.isfinite(self.max_failsafe_age_s) or self.max_failsafe_age_s <= 0.0:
            raise ValueError("max_failsafe_age_s must be a positive finite number")
        if set(self.stream_max_age_s) != set(REQUIRED_STREAMS):
            raise ValueError("stream_max_age_s must give a limit for every required stream")
        for stream, limit in self.stream_max_age_s.items():
            if (
                isinstance(limit, bool)
                or not isinstance(limit, int | float)
                or not math.isfinite(limit)
                or limit <= 0.0
            ):
                raise ValueError(f"stream_max_age_s[{stream.name}] must be positive and finite")


def normalize_flight_mode(mode: object) -> str:
    """Return an upper-case PX4 mode name from a MAVSDK enum member or string.

    MAVSDK's ``telemetry.FlightMode`` members expose ``.name`` (e.g. ``HOLD``,
    ``RETURN_TO_LAUNCH``). Anything that is not a non-empty string or enum-like
    object becomes ``UNKNOWN``, which the gate treats as not delegated.
    """

    name = getattr(mode, "name", mode)
    if not isinstance(name, str):
        return UNKNOWN_MODE
    name = name.strip().upper()
    return name or UNKNOWN_MODE


def battery_fraction_from_percent(remaining_percent: object) -> float | None:
    """Convert MAVSDK 3.x ``remaining_percent`` (0-100) to a 0.0-1.0 fraction.

    Returns ``None`` (unknown) for non-numeric, non-finite or out-of-range input
    rather than clamping, so a unit or sensor error cannot look like a charge.
    """

    if isinstance(remaining_percent, bool) or not isinstance(remaining_percent, int | float):
        return None
    value = float(remaining_percent)
    if not math.isfinite(value) or not 0.0 <= value <= 100.0:
        return None
    return value / 100.0


class TelemetryTracker:
    """Holds the latest value and receive time of each telemetry stream."""

    def __init__(self, config: TelemetryTrackerConfig | None = None) -> None:
        self._config = config or TelemetryTrackerConfig()
        self._config.validate()
        self._values: dict[Stream, object] = {}
        self._times: dict[Stream, float] = {}
        self._failsafe: bool | None = None
        self._failsafe_time: float | None = None

    # ----------------------------------------------------------- updates
    def update_flight_mode(self, mode: object, now_s: float) -> None:
        self._set(Stream.FLIGHT_MODE, normalize_flight_mode(mode), now_s, valid=True)

    def update_armed(self, armed: object, now_s: float) -> None:
        self._set(Stream.ARMED, armed, now_s, valid=isinstance(armed, bool))

    def update_in_air(self, in_air: object, now_s: float) -> None:
        self._set(Stream.IN_AIR, in_air, now_s, valid=isinstance(in_air, bool))

    def update_position(self, relative_altitude_m: object, now_s: float) -> None:
        valid = (
            isinstance(relative_altitude_m, int | float)
            and not isinstance(relative_altitude_m, bool)
            and math.isfinite(relative_altitude_m)
        )
        self._set(Stream.POSITION, relative_altitude_m, now_s, valid=valid)

    def update_battery_percent(self, remaining_percent: object, now_s: float) -> None:
        """Record battery from MAVSDK's 0-100 ``remaining_percent``.

        An out-of-range reading is stored as unknown (``None``) but still counts
        as a fresh battery message; the gate then refuses takeoff and goto.
        """

        fraction = battery_fraction_from_percent(remaining_percent)
        self._set(Stream.BATTERY, fraction, now_s, valid=True)

    def update_failsafe(self, active: bool | None, now_s: float) -> None:
        """Record PX4 failsafe state from a source still to be chosen."""

        _require_finite_time(now_s)
        if self._failsafe_time is not None and now_s < self._failsafe_time:
            return
        self._failsafe = active if isinstance(active, bool) else None
        self._failsafe_time = now_s

    # ----------------------------------------------------------- outputs
    def missing_streams(self) -> tuple[Stream, ...]:
        return tuple(s for s in REQUIRED_STREAMS if s not in self._values)

    def failsafe_active(self, now_s: float) -> bool | None:
        """Latest failsafe state, or ``None`` if never received, stale or unknown."""

        if self._failsafe_time is None or not math.isfinite(now_s):
            return None
        age = now_s - self._failsafe_time
        if age < 0.0 or age > self._config.max_failsafe_age_s:
            return None
        return self._failsafe

    def snapshot(self, now_s: float) -> VehicleSnapshot:
        """Build a snapshot of the latest values.

        ``telemetry_age_s`` is infinite if any required stream is missing or
        malformed; the age of the oldest stream if any stream is past its own
        limit; otherwise the age of the newest update (link liveness).
        ``operator_delegated`` is always False here; only
        :meth:`DelegationAuthority.apply_to` may set it.
        """

        age = math.inf
        if not self.missing_streams() and math.isfinite(now_s):
            limits = self._config.stream_max_age_s
            ages = {s: now_s - self._times[s] for s in REQUIRED_STREAMS}
            if any(a < 0.0 for a in ages.values()):
                age = math.inf
            elif all(a <= limits[s] for s, a in ages.items()):
                age = min(ages.values())
            else:
                # A stream is past its own limit: report the oldest age so the
                # authority revokes as TELEMETRY_LINK_LOST (this assumes every
                # per-stream limit is at least the authority/gate age limit).
                age = max(ages.values())
        return VehicleSnapshot(
            flight_mode=self._values.get(Stream.FLIGHT_MODE, UNKNOWN_MODE),
            armed=self._values.get(Stream.ARMED, False),
            in_air=self._values.get(Stream.IN_AIR, False),
            relative_altitude_m=float(self._values.get(Stream.POSITION, math.nan)),
            battery_remaining_fraction=self._values.get(Stream.BATTERY),
            telemetry_age_s=age,
        )

    # ---------------------------------------------------------- internals
    def _set(self, stream: Stream, value: object, now_s: float, *, valid: bool) -> None:
        _require_finite_time(now_s)
        last = self._times.get(stream)
        if last is not None and now_s < last:
            return  # out-of-order delivery; keep the newer value
        if not valid:
            # Malformed value: forget the stream so the snapshot becomes unknown.
            self._values.pop(stream, None)
            self._times.pop(stream, None)
            return
        self._values[stream] = value
        self._times[stream] = now_s


def _require_finite_time(now_s: float) -> None:
    if not isinstance(now_s, int | float) or not math.isfinite(now_s):
        raise ValueError("telemetry timestamp must be a finite monotonic time")


def observe_vehicle(
    tracker: TelemetryTracker, authority: DelegationAuthority, now_s: float
) -> VehicleSnapshot:
    """Feed the tracker's current state to ``authority`` and return the snapshot.

    Call this on every telemetry tick (and before handling a ground-station
    grant) so R6 revocations happen even when no request is pending.
    """

    snapshot = tracker.snapshot(now_s)
    authority.observe(snapshot, tracker.failsafe_active(now_s), now_s)
    return snapshot


def evaluate_companion_request(
    request: ActionRequest,
    tracker: TelemetryTracker,
    authority: DelegationAuthority,
    now_s: float,
    limits: AdvisoryLimits | None = None,
) -> GateDecision:
    """One evaluation step: tracker -> delegation authority -> action gate.

    Observes first (which may revoke and queue an alert), then evaluates
    ``request`` with ``operator_delegated`` taken only from the authority. The
    caller still owns forwarding an ALLOW decision to PX4; this sends nothing.
    """

    snapshot = observe_vehicle(tracker, authority, now_s)
    return evaluate_request(request, authority.apply_to(snapshot, now_s), limits)
