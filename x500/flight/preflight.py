"""Companion-side readiness gate before a waypoint mission is uploaded or armed.

Part of the multirotor flight layer that the X500 proves and Coyote is meant to
reuse (owner decision 2026-10-21: the X500 is waypoint autonomy only). It is
aircraft-agnostic; per-aircraft numbers arrive through :class:`PreflightLimits`,
whose values are **model inputs**.

Gap it closes
-------------
The SITL mission scripts waited only for global-position and home health, then
uploaded a mission and requested arm. Nothing checked that the vehicle was
still disarmed and on the ground. Uploading to an armed or airborne vehicle
replaces the mission PX4 may already be flying, and requesting arm then
``start_mission`` would take over an aircraft someone else is operating. The
gate refuses in those cases and when the battery reading or PX4's own
readiness flags do not support starting a mission.

Authority boundary
------------------
The gate only *withholds* requests. It never arms, uploads or commands
anything, and passing it does not make arming happen: PX4 arming checks stay
enabled and authoritative, and PX4 keeps battery, geofence and link-loss
failsafes, RTL and pilot override. ``is_armable`` is PX4's pre-arm verdict as
reported by MAVSDK; the gate defers to it rather than replacing it.

Every value must be positively known: a missing, malformed or non-boolean
reading is a refusal, never a pass.

Evidence status
---------------
Unit-tested only. MAVSDK-Python 3.17.2 ``telemetry.Health`` and
``telemetry.Battery`` field names (and the 0-100 scale of
``Battery.remaining_percent``) were checked against the installed package
without a vehicle. **Not run against PX4 SITL.**
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# PX4 health flags (MAVSDK ``telemetry.Health``) that must all be True.
REQUIRED_HEALTH_FLAGS = (
    "is_gyrometer_calibration_ok",
    "is_accelerometer_calibration_ok",
    "is_magnetometer_calibration_ok",
    "is_local_position_ok",
    "is_global_position_ok",
    "is_home_position_ok",
    "is_armable",
)


class PreflightRefused(RuntimeError):
    """The companion withheld upload/arm because the vehicle is not ready."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class PreflightLimits:
    """Companion-side readiness thresholds. **Model inputs**, per aircraft.

    ``min_battery_fraction`` (0-1) is not a battery reserve calculation or an
    endurance claim; it must be set at or above, never below, the PX4 battery
    failsafe thresholds (``BAT_LOW_THR`` and friends).
    """

    min_battery_fraction: float
    max_telemetry_age_s: float

    def validate(self) -> None:
        if not (
            isinstance(self.min_battery_fraction, int | float)
            and math.isfinite(self.min_battery_fraction)
            and 0.0 < self.min_battery_fraction <= 1.0
        ):
            raise ValueError("min_battery_fraction must be in (0, 1]")
        if not (
            isinstance(self.max_telemetry_age_s, int | float)
            and math.isfinite(self.max_telemetry_age_s)
            and self.max_telemetry_age_s > 0.0
        ):
            raise ValueError("max_telemetry_age_s must be a positive finite number")


@dataclass(frozen=True)
class PreflightSample:
    """One reading of each stream; ``oldest_at_s`` is the oldest receive time."""

    armed: object
    in_air: object
    battery_fraction: float | None
    health: dict[str, object]
    oldest_at_s: float


def battery_fraction_from_percent(remaining_percent: object) -> float | None:
    """MAVSDK 3.x ``remaining_percent`` (0-100) -> 0-1, or ``None`` if implausible.

    Out-of-range values are not clamped, so a unit error cannot look like charge.
    (Same rule as ``coyote.autonomy.telemetry``; the flight layer does not import
    Coyote code.)
    """

    if isinstance(remaining_percent, bool) or not isinstance(remaining_percent, int | float):
        return None
    value = float(remaining_percent)
    if not math.isfinite(value) or not 0.0 <= value <= 100.0:
        return None
    return value / 100.0


def preflight_refusals(
    sample: PreflightSample | None, now_s: float, limits: PreflightLimits
) -> tuple[str, ...]:
    """Return every reason not to upload/arm; an empty tuple means ready."""

    limits.validate()
    if sample is None:
        return ("no preflight telemetry received",)
    reasons: list[str] = []
    age = now_s - sample.oldest_at_s
    if not (math.isfinite(sample.oldest_at_s) and math.isfinite(now_s)):
        reasons.append("telemetry timestamp is not finite")
    elif age < 0.0:
        reasons.append("telemetry timestamp is in the future")
    elif age > limits.max_telemetry_age_s:
        reasons.append(f"telemetry is {age:.1f} s old (limit {limits.max_telemetry_age_s:.1f} s)")

    if sample.armed is not False:
        reasons.append(
            "vehicle is already armed" if sample.armed is True else "armed state unknown"
        )
    if sample.in_air is not False:
        reasons.append("vehicle is in the air" if sample.in_air is True else "in-air state unknown")

    fraction = sample.battery_fraction
    if fraction is None:
        reasons.append("battery level unknown")
    elif fraction < limits.min_battery_fraction:
        reasons.append(
            f"battery {fraction:.0%} below companion minimum {limits.min_battery_fraction:.0%}"
        )

    for flag in REQUIRED_HEALTH_FLAGS:
        value = sample.health.get(flag)
        if value is not True:
            state = "False" if value is False else "unknown"
            reasons.append(f"PX4 health {flag} is {state}")
    return tuple(reasons)


async def read_preflight_sample(
    drone: Any, timeout_s: float, clock: Callable[[], float]
) -> PreflightSample:
    """Read the first value of armed, in-air, battery and health (read-only).

    Raises ``asyncio.TimeoutError`` if any stream is silent for ``timeout_s``
    and ``RuntimeError`` if a stream ends without a value. Sends nothing.
    """

    async def first(stream_factory: Callable[[], Any], name: str) -> tuple[object, float]:
        async for value in stream_factory():
            return value, clock()
        raise RuntimeError(f"{name} telemetry stream ended before a value")

    telemetry = drone.telemetry
    (armed, t1), (in_air, t2), (battery, t3), (health, t4) = await asyncio.wait_for(
        asyncio.gather(
            first(telemetry.armed, "armed"),
            first(telemetry.in_air, "in-air"),
            first(telemetry.battery, "battery"),
            first(telemetry.health, "health"),
        ),
        timeout=timeout_s,
    )
    return PreflightSample(
        armed=armed,
        in_air=in_air,
        battery_fraction=battery_fraction_from_percent(getattr(battery, "remaining_percent", None)),
        health={flag: getattr(health, flag, None) for flag in REQUIRED_HEALTH_FLAGS},
        oldest_at_s=min(t1, t2, t3, t4),
    )


async def require_preflight_ready(
    drone: Any, limits: PreflightLimits, timeout_s: float, clock: Callable[[], float]
) -> PreflightSample:
    """Read a fresh sample and raise :class:`PreflightRefused` unless ready."""

    sample = await read_preflight_sample(drone, timeout_s, clock)
    reasons = preflight_refusals(sample, clock(), limits)
    if reasons:
        raise PreflightRefused(reasons)
    return sample
