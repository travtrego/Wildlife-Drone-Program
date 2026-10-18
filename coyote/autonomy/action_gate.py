"""Companion-side gate for Coyote mission action requests.

The Jetson perception/mission layer proposes actions (hold, go to a local
position, return to launch, land). Before any such request is forwarded to PX4,
this module decides deterministically whether the companion computer should
send it at all, given the latest PX4 telemetry snapshot.

Authority boundary
------------------
* PX4 remains authoritative for stabilization, geofence, battery and link-loss
  failsafes, RTL and pilot override. Nothing here replaces or relaxes those.
* This gate only makes the companion computer *more* conservative: it refuses
  to send requests while the pilot or an autopilot recovery mode owns the
  aircraft, when telemetry is stale or unknown, or when a request falls outside
  companion-side advisory limits that should sit inside the PX4 limits.
* A REJECT verdict may carry a ``recommended`` action. That is a proposal for
  the mission layer/operator; this module never issues it.

The module has no MAVSDK, ROS or hardware dependency so it can be exercised
by unit tests without a simulator or aircraft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class ActionKind(Enum):
    HOLD = "hold"
    GOTO_LOCAL = "goto_local"
    RETURN_TO_LAUNCH = "return_to_launch"
    LAND = "land"


# Actions that reduce energy/risk rather than extend the flight.
DE_ESCALATING_ACTIONS = frozenset({ActionKind.HOLD, ActionKind.RETURN_TO_LAUNCH, ActionKind.LAND})

# PX4 flight-mode names as reported by MAVSDK ``telemetry.flight_mode()``.
# Modes in which a pilot is flying through the RC sticks: the companion yields.
PILOT_CONTROLLED_MODES = frozenset(
    {"MANUAL", "STABILIZED", "ALTCTL", "POSCTL", "ACRO", "RATTITUDE"}
)
# Autopilot-owned recovery modes (commanded or failsafe): never fight them.
AUTOPILOT_RECOVERY_MODES = frozenset({"RETURN_TO_LAUNCH", "LAND"})
# Modes in which the operator has delegated mission actions to the companion.
COMPANION_DELEGATED_MODES = frozenset({"HOLD", "MISSION", "OFFBOARD"})


class Verdict(Enum):
    ALLOW = "allow"
    REJECT = "reject"


@dataclass(frozen=True)
class ActionRequest:
    """An action proposed by the mission layer.

    ``north_m``/``east_m``/``altitude_m`` are only used for ``GOTO_LOCAL`` and
    are relative to the PX4 home position (altitude above home, positive up).
    """

    kind: ActionKind
    north_m: float = 0.0
    east_m: float = 0.0
    altitude_m: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class VehicleSnapshot:
    """Latest PX4 state as seen by the companion computer."""

    flight_mode: str
    armed: bool
    in_air: bool
    relative_altitude_m: float
    battery_remaining_fraction: float | None
    telemetry_age_s: float
    # Explicit operator authorization for companion autonomy. A PX4 flight mode
    # alone cannot prove delegation (e.g. HOLD may be pilot- or failsafe-set),
    # so the gate rejects everything unless this is True. How it is sourced
    # (RC aux switch, GCS command, ...) is an open design decision.
    operator_delegated: bool = False


@dataclass(frozen=True)
class AdvisoryLimits:
    """Companion-side advisory limits.

    MODEL INPUTS / PLACEHOLDERS: these defaults are conservative development
    values for simulation. They are not derived from Coyote flight testing,
    do not represent a validated envelope, and must be set inside (never
    looser than) the PX4 geofence and battery failsafe parameters configured
    on the autopilot.
    """

    max_altitude_m: float = 60.0
    min_altitude_m: float = 5.0
    max_distance_from_home_m: float = 150.0
    min_battery_fraction_for_goto: float = 0.40
    max_telemetry_age_s: float = 1.0

    def validate(self) -> None:
        values = (
            self.max_altitude_m,
            self.min_altitude_m,
            self.max_distance_from_home_m,
            self.min_battery_fraction_for_goto,
            self.max_telemetry_age_s,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Advisory limits must be finite numbers")
        if not 0.0 < self.min_altitude_m < self.max_altitude_m:
            raise ValueError("Require 0 < min_altitude_m < max_altitude_m")
        if self.max_altitude_m > 120.0:
            # Stay at or below the ~400 ft AGL Part 107 ceiling by default.
            raise ValueError("max_altitude_m above 120 m is not allowed by this gate")
        if self.max_distance_from_home_m <= 0.0:
            raise ValueError("max_distance_from_home_m must be positive")
        if not 0.0 < self.min_battery_fraction_for_goto < 1.0:
            raise ValueError("min_battery_fraction_for_goto must be between 0 and 1")
        if self.max_telemetry_age_s <= 0.0:
            raise ValueError("max_telemetry_age_s must be positive")


@dataclass(frozen=True)
class GateDecision:
    verdict: Verdict
    reasons: tuple[str, ...]
    recommended: ActionKind | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


def _reject(*reasons: str, recommended: ActionKind | None = None) -> GateDecision:
    return GateDecision(Verdict.REJECT, tuple(reasons), recommended)


def evaluate_request(
    request: ActionRequest,
    vehicle: VehicleSnapshot,
    limits: AdvisoryLimits | None = None,
) -> GateDecision:
    """Decide whether the companion computer may forward ``request`` to PX4.

    Checks run in a fixed order so that the most authoritative reason to stand
    down (unknown state, pilot, autopilot recovery) is always reported first.
    """

    limits = limits or AdvisoryLimits()
    limits.validate()
    mode = vehicle.flight_mode.strip().upper()

    # 1. Unknown or stale state: do not act on it. PX4 link-loss failsafe owns
    #    the aircraft if the companion cannot see it.
    if not math.isfinite(vehicle.telemetry_age_s) or vehicle.telemetry_age_s < 0:
        return _reject("telemetry age is invalid")
    if vehicle.telemetry_age_s > limits.max_telemetry_age_s:
        return _reject(
            f"telemetry is stale ({vehicle.telemetry_age_s:.2f} s > "
            f"{limits.max_telemetry_age_s:.2f} s)"
        )

    # 2. Pilot override: the companion yields completely, including de-escalation.
    if mode in PILOT_CONTROLLED_MODES:
        return _reject(f"pilot has control in {mode}; companion yields")

    # 3. Autopilot recovery (RTL/LAND, commanded or failsafe): do not interfere.
    if mode in AUTOPILOT_RECOVERY_MODES:
        return _reject(f"PX4 recovery mode {mode} in progress; companion yields")

    # 4. Anything not explicitly delegated is treated as not ours.
    if mode not in COMPANION_DELEGATED_MODES:
        return _reject(f"flight mode {mode or '<empty>'} is not delegated to companion")

    if not vehicle.operator_delegated:
        return _reject("operator has not delegated mission actions to companion")

    # 5. This gate covers in-flight requests only; arming/takeoff stay with
    #    the operator and PX4.
    if not (vehicle.armed and vehicle.in_air):
        return _reject("vehicle is not armed and airborne")

    # 6. De-escalating actions are allowed once the above hold.
    if request.kind in DE_ESCALATING_ACTIONS:
        return GateDecision(Verdict.ALLOW, (f"{request.kind.value} reduces mission risk",))

    if request.kind is not ActionKind.GOTO_LOCAL:  # pragma: no cover - enum is closed
        return _reject(f"unsupported action {request.kind!r}")

    return _evaluate_goto(request, vehicle, limits)


def _evaluate_goto(
    request: ActionRequest, vehicle: VehicleSnapshot, limits: AdvisoryLimits
) -> GateDecision:
    target = (request.north_m, request.east_m, request.altitude_m)
    if not all(math.isfinite(v) for v in target):
        return _reject("goto target contains non-finite values")

    battery = vehicle.battery_remaining_fraction
    if battery is None or not math.isfinite(battery):
        return _reject(
            "battery state unknown; refusing to extend flight",
            recommended=ActionKind.RETURN_TO_LAUNCH,
        )
    if battery < limits.min_battery_fraction_for_goto:
        return _reject(
            f"battery {battery:.0%} below advisory goto reserve "
            f"{limits.min_battery_fraction_for_goto:.0%}",
            recommended=ActionKind.RETURN_TO_LAUNCH,
        )

    reasons: list[str] = []
    if not limits.min_altitude_m <= request.altitude_m <= limits.max_altitude_m:
        reasons.append(
            f"target altitude {request.altitude_m:.1f} m outside advisory "
            f"[{limits.min_altitude_m:.1f}, {limits.max_altitude_m:.1f}] m"
        )
    distance = math.hypot(request.north_m, request.east_m)
    if distance > limits.max_distance_from_home_m:
        reasons.append(
            f"target {distance:.1f} m from home exceeds advisory "
            f"{limits.max_distance_from_home_m:.1f} m"
        )
    if reasons:
        return _reject(*reasons, recommended=ActionKind.HOLD)

    return GateDecision(Verdict.ALLOW, ("goto target within advisory limits",))
