"""Turn per-stream PX4 telemetry into the gate's :class:`VehicleSnapshot`.

MAVSDK delivers vehicle state as independent async streams (flight mode,
armed, in-air, position, battery). The action gate and delegation authority
need one :class:`~coyote.autonomy.action_gate.VehicleSnapshot` whose
``telemetry_age_s`` honestly reflects how old the *oldest* of those values is.
This module is that adapter, with no MAVSDK import so it stays unit-testable:
the future MAVSDK task only calls ``update_*`` with values it receives and a
monotonic timestamp.

Conservative rules (implementation choices, not new owner requirements)
----------------------------------------------------------------------
* **Oldest stream sets the age.** ``telemetry_age_s`` is ``now`` minus the
  oldest required stream update, so one silent stream makes the whole snapshot
  stale even if other streams keep arriving.
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
* **Failsafe state is a separate input.** Which MAVLink/MAVSDK signal provides
  ``failsafe_active`` is still an open choice (see ``delegation.py``). Until a
  source calls :meth:`TelemetryTracker.update_failsafe`, or when its value is
  older than ``max_failsafe_age_s``, :meth:`TelemetryTracker.failsafe_active`
  returns ``None`` and the delegation authority treats that as unsafe.

Nothing here commands the vehicle. Timing defaults are MODEL INPUTS /
development placeholders, not tested values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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


@dataclass(frozen=True)
class TelemetryTrackerConfig:
    """MODEL INPUT / PLACEHOLDER: not derived from SITL or flight testing."""

    max_failsafe_age_s: float = 1.0

    def validate(self) -> None:
        if not math.isfinite(self.max_failsafe_age_s) or self.max_failsafe_age_s <= 0.0:
            raise ValueError("max_failsafe_age_s must be a positive finite number")


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
        """Build a snapshot whose age is that of the oldest required stream.

        ``operator_delegated`` is always False here; only
        :meth:`DelegationAuthority.apply_to` may set it.
        """

        if self.missing_streams() or not math.isfinite(now_s):
            age = math.inf
        else:
            age = now_s - min(self._times[s] for s in REQUIRED_STREAMS)
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
