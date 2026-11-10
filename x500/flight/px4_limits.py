"""Read-only check that companion limits sit inside the PX4 limits they rely on.

Part of the multirotor flight layer that the X500 proves and Coyote is meant to
reuse (owner decision 2026-10-21: the X500 is waypoint autonomy only). It is
aircraft-agnostic: the companion limits arrive as :class:`MultirotorMissionLimits`
and :class:`PreflightLimits` (per-aircraft **model inputs**), and the PX4
values are read from the connected vehicle.

Gap it closes
-------------
``MultirotorMissionLimits`` and ``PreflightLimits`` say they "must sit inside,
never looser than" the PX4 geofence, speed and battery failsafe parameters, but
nothing checked that. A companion ceiling above ``GF_MAX_VER_DIST`` or a
companion battery minimum below ``BAT_LOW_THR`` would let the companion accept
a mission that PX4's own failsafe is set to interrupt, or rely on a margin that
PX4 does not enforce. This check reads those parameters once before upload and
refuses on any contradiction.

The same holds inside PX4: the flight script ends every mission by requesting
PX4 RTL, and with the PX4 default ``RTL_RETURN_ALT`` (60 m) above the SITL
checklist's vertical geofence (40 m) the return would climb into the fence.
``RTL_RETURN_ALT`` is therefore read and checked against ``GF_MAX_VER_DIST``.

Rules (implementation choices, not owner requirements)
------------------------------------------------------
- Every parameter must be read and be a finite number. An unreadable, missing,
  non-numeric or negative value is a refusal, never a pass.
- ``GF_MAX_HOR_DIST`` / ``GF_MAX_VER_DIST`` (m): must be enabled (> 0) and the
  companion distance-from-home / ceiling must be at or below them. ``0`` means
  PX4 does not enforce that limit (PX4 default) and is a **refusal**: without
  it there is no PX4 backstop behind the companion limit (owner decision
  2026-11-06).
- ``GF_ACTION`` must make PX4 act on a breach: Hold (2), Return (3) or Land
  (5). None (0) and Warning (1) do not stop the vehicle and refuse. Terminate
  (4) and any other value also refuse; whether Terminate is acceptable on a
  real aircraft is not decided here. The numeric meanings are from PX4
  documentation as known to this change, not read from the SITL build.
- ``MPC_XY_VEL_MAX`` (m/s, must be > 0): the companion max speed must be at or
  below it, otherwise PX4 would cap the flown speed below the verified one.
- ``BAT_LOW_THR`` (fraction, must be in (0, 1)): the companion battery minimum
  must be at or above it.
- ``RTL_RETURN_ALT`` (m above home, must be >= 0): must be at or below an
  enabled ``GF_MAX_VER_DIST``. PX4 RTL climbs to this altitude before heading
  home (PX4 default 60 m), so a value above the vertical geofence makes PX4's
  own return fly into its own fence, on the one path the companion relies on
  to end every mission. Treated as the worst-case return altitude: the
  ``RTL_CONE_ANG`` reduction near home is not modelled (it only lowers the
  climb). It is not compared with the companion ceiling; whether PX4's return
  may climb above the companion ceiling is an open owner question.

Authority boundary
------------------
Read-only. It never sets a parameter, uploads, arms or commands anything. It
only *withholds* the mission; passing it does not mean PX4's geofence or
failsafes are correctly tuned for an aircraft, only that the companion limits
do not contradict them. PX4 keeps geofence, failsafes, RTL and pilot override.

Evidence status
---------------
Unit-tested only with fake parameter readers. The parameter names and units are
from PX4 documentation as known to this change and were **not** checked against
the PX4 build used in SITL (``6041c961``); a renamed or missing parameter makes
the check refuse rather than pass. MAVSDK-Python ``param.get_param_float`` /
``get_param_int`` are the assumed read calls. Not yet run in PX4 SITL. The
interaction between PX4 RTL and the vertical geofence (whether PX4 would
actually breach, warn or clamp) is not observed; the check only refuses the
configuration in which the documented RTL climb exceeds the fence.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

from x500.flight.preflight import PreflightLimits
from x500.flight.waypoint_mission import MultirotorMissionLimits

# PX4 parameter name -> MAVSDK value type ("float" or "int").
PX4_LIMIT_PARAMS: dict[str, str] = {
    "GF_MAX_HOR_DIST": "float",
    "GF_MAX_VER_DIST": "float",
    "GF_ACTION": "int",
    "MPC_XY_VEL_MAX": "float",
    "BAT_LOW_THR": "float",
    "RTL_RETURN_ALT": "float",
}

# PX4 GF_ACTION values (PX4 documentation; not read from the SITL build).
GF_ACTION_NAMES: dict[int, str] = {
    0: "None",
    1: "Warning",
    2: "Hold",
    3: "Return",
    4: "Terminate",
    5: "Land",
}
# Breach actions that make PX4 itself stop the mission (owner decision 2026-11-06).
GF_ACTIONS_ACCEPTED: frozenset[int] = frozenset({2, 3, 5})


class Px4LimitsRefused(RuntimeError):
    """The companion withheld the mission: its limits contradict PX4's."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class Px4LimitReport:
    """Result of one check. ``values`` holds what was read (or the read error)."""

    values: dict[str, object]
    refusals: tuple[str, ...]

    @property
    def consistent(self) -> bool:
        return not self.refusals


def _number(values: dict[str, object], name: str, refusals: list[str]) -> float | None:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        detail = f": {value}" if isinstance(value, str) else ""
        refusals.append(f"PX4 {name} not read as a number{detail}")
        return None
    number = float(value)
    if not math.isfinite(number):
        refusals.append(f"PX4 {name} is not finite ({value!r})")
        return None
    return number


def _check_geofence(
    values: dict[str, object],
    name: str,
    companion: float,
    what: str,
    refusals: list[str],
) -> None:
    px4 = _number(values, name, refusals)
    if px4 is None:
        return
    if px4 < 0.0:
        refusals.append(f"PX4 {name} is negative ({px4:g})")
    elif px4 == 0.0:
        refusals.append(
            f"PX4 {name} = 0: PX4 does not enforce the {what} ({companion:g} m); "
            f"set a PX4 geofence at or above it"
        )
    elif companion > px4:
        refusals.append(f"companion {what} {companion:g} m is looser than PX4 {name} {px4:g} m")


def px4_limit_findings(
    values: dict[str, object],
    mission_limits: MultirotorMissionLimits,
    preflight_limits: PreflightLimits,
) -> Px4LimitReport:
    """Compare companion limits with PX4 parameter values. Pure function."""

    mission_limits.validate()
    preflight_limits.validate()
    refusals: list[str] = []

    _check_geofence(
        values,
        "GF_MAX_HOR_DIST",
        mission_limits.max_distance_from_home_m,
        "distance-from-home limit",
        refusals,
    )
    _check_geofence(
        values,
        "GF_MAX_VER_DIST",
        mission_limits.max_relative_altitude_m,
        "altitude ceiling",
        refusals,
    )

    action = values.get("GF_ACTION")
    if isinstance(action, bool) or not isinstance(action, int):
        detail = f": {action}" if isinstance(action, str) else ""
        refusals.append(f"PX4 GF_ACTION not read as an integer{detail}")
    elif action not in GF_ACTIONS_ACCEPTED:
        meaning = GF_ACTION_NAMES.get(action, "unknown value")
        refusals.append(
            f"PX4 GF_ACTION = {action} ({meaning}): accepted breach actions are "
            + ", ".join(f"{GF_ACTION_NAMES[a]} ({a})" for a in sorted(GF_ACTIONS_ACCEPTED))
        )

    speed = _number(values, "MPC_XY_VEL_MAX", refusals)
    if speed is not None:
        if speed <= 0.0:
            refusals.append(f"PX4 MPC_XY_VEL_MAX is not positive ({speed:g})")
        elif mission_limits.max_speed_m_s > speed:
            refusals.append(
                f"companion max speed {mission_limits.max_speed_m_s:g} m/s is above "
                f"PX4 MPC_XY_VEL_MAX {speed:g} m/s"
            )

    low = _number(values, "BAT_LOW_THR", refusals)
    if low is not None:
        if not 0.0 < low < 1.0:
            refusals.append(f"PX4 BAT_LOW_THR outside (0, 1) ({low:g})")
        elif preflight_limits.min_battery_fraction < low:
            refusals.append(
                f"companion battery minimum {preflight_limits.min_battery_fraction:.0%} is "
                f"below PX4 BAT_LOW_THR {low:.0%}"
            )

    _check_return_altitude(values, refusals)

    return Px4LimitReport(values=dict(values), refusals=tuple(refusals))


def _check_return_altitude(values: dict[str, object], refusals: list[str]) -> None:
    """PX4's RTL climb must not reach above PX4's own vertical geofence."""

    rtl_alt = _number(values, "RTL_RETURN_ALT", refusals)
    if rtl_alt is None:
        return
    if rtl_alt < 0.0:
        refusals.append(f"PX4 RTL_RETURN_ALT is negative ({rtl_alt:g})")
        return
    fence = values.get("GF_MAX_VER_DIST")
    if isinstance(fence, bool) or not isinstance(fence, int | float):
        return  # already refused by the geofence check
    fence = float(fence)
    if not math.isfinite(fence) or fence <= 0.0:
        return  # disabled or invalid fence is already a refusal
    if rtl_alt > fence:
        refusals.append(
            f"PX4 RTL_RETURN_ALT {rtl_alt:g} m is above PX4 GF_MAX_VER_DIST {fence:g} m: "
            f"PX4's return would climb into its own vertical geofence"
        )


async def read_px4_limit_params(drone: Any, timeout_s: float) -> dict[str, object]:
    """Read each limit parameter once. A failed read is stored as its error text."""

    values: dict[str, object] = {}
    for name, kind in PX4_LIMIT_PARAMS.items():
        getter = drone.param.get_param_int if kind == "int" else drone.param.get_param_float
        try:
            values[name] = await asyncio.wait_for(getter(name), timeout_s)
        except TimeoutError:
            values[name] = f"no reply within {timeout_s:g} s"
        except Exception as exc:  # MAVSDK ParamError and transport errors
            values[name] = f"read failed ({type(exc).__name__}: {exc})"
    return values


async def require_px4_limits_consistent(
    drone: Any,
    mission_limits: MultirotorMissionLimits,
    preflight_limits: PreflightLimits,
    timeout_s: float,
) -> Px4LimitReport:
    """Read the PX4 limits and raise :class:`Px4LimitsRefused` on any contradiction."""

    values = await read_px4_limit_params(drone, timeout_s)
    report = px4_limit_findings(values, mission_limits, preflight_limits)
    if report.refusals:
        raise Px4LimitsRefused(report.refusals)
    return report
