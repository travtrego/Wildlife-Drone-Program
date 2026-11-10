"""Companion-limit vs PX4-parameter consistency check (x500.flight.px4_limits)."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from x500.flight.preflight import PreflightLimits
from x500.flight.px4_limits import (
    PX4_LIMIT_PARAMS,
    Px4LimitsRefused,
    px4_limit_findings,
    read_px4_limit_params,
    require_px4_limits_consistent,
)
from x500.flight.settings import X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS
from x500.flight.waypoint_mission import MultirotorMissionLimits

MISSION = MultirotorMissionLimits(
    max_relative_altitude_m=30.0,
    min_waypoint_altitude_m=3.0,
    max_distance_from_home_m=100.0,
    max_speed_m_s=5.0,
    max_waypoints=20,
)
PREFLIGHT = PreflightLimits(min_battery_fraction=0.4, max_telemetry_age_s=2.0)

# Geofence enabled and every companion limit inside it.
ENFORCED = {
    "GF_MAX_HOR_DIST": 150.0,
    "GF_MAX_VER_DIST": 40.0,
    "GF_ACTION": 3,
    "MPC_XY_VEL_MAX": 12.0,
    "BAT_LOW_THR": 0.15,
    "RTL_RETURN_ALT": 20.0,
}
# PX4 defaults as documented (horizontal/vertical geofence disabled, RTL at 60 m).
PX4_DEFAULTS = {
    **ENFORCED,
    "GF_MAX_HOR_DIST": 0.0,
    "GF_MAX_VER_DIST": 0.0,
    "GF_ACTION": 2,
    "RTL_RETURN_ALT": 60.0,
}


def findings(**overrides):
    return px4_limit_findings({**ENFORCED, **overrides}, MISSION, PREFLIGHT)


def test_companion_inside_enforced_px4_limits_passes() -> None:
    report = findings()
    assert report.consistent and report.refusals == ()


def test_equal_limits_are_not_looser() -> None:
    report = findings(
        GF_MAX_HOR_DIST=100.0, GF_MAX_VER_DIST=30.0, MPC_XY_VEL_MAX=5.0, BAT_LOW_THR=0.4
    )
    assert report.consistent


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"GF_MAX_HOR_DIST": 80.0},
            "distance-from-home limit 100 m is looser than PX4 GF_MAX_HOR_DIST 80",
        ),
        ({"GF_MAX_VER_DIST": 25.0}, "ceiling 30 m is looser than PX4 GF_MAX_VER_DIST 25 m"),
        ({"MPC_XY_VEL_MAX": 4.0}, "max speed 5 m/s is above PX4 MPC_XY_VEL_MAX 4 m/s"),
        ({"BAT_LOW_THR": 0.5}, "battery minimum 40% is below PX4 BAT_LOW_THR 50%"),
    ],
)
def test_companion_looser_than_px4_refuses(overrides, expected) -> None:
    report = findings(**overrides)
    assert not report.consistent
    assert any(expected in r for r in report.refusals), report.refusals


def test_all_contradictions_are_reported_together() -> None:
    report = findings(GF_MAX_HOR_DIST=50.0, GF_MAX_VER_DIST=10.0, BAT_LOW_THR=0.6)
    # Three companion contradictions plus RTL_RETURN_ALT (20 m) above the 10 m fence.
    assert len(report.refusals) == 4


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GF_MAX_HOR_DIST", "GF_MAX_HOR_DIST = 0: PX4 does not enforce the distance-from-home"),
        ("GF_MAX_VER_DIST", "GF_MAX_VER_DIST = 0: PX4 does not enforce the altitude ceiling"),
    ],
)
def test_disabled_px4_geofence_limit_refuses(name, expected) -> None:
    # Owner decision 2026-11-06: no PX4 backstop means no mission.
    report = findings(**{name: 0.0})
    assert not report.consistent
    assert any(expected in r for r in report.refusals), report.refusals


@pytest.mark.parametrize("action", [2, 3, 5])
def test_breach_actions_that_stop_the_vehicle_pass(action) -> None:
    assert findings(GF_ACTION=action).consistent


@pytest.mark.parametrize(
    ("action", "meaning"),
    [(0, "None"), (1, "Warning"), (4, "Terminate"), (6, "unknown value"), (-1, "unknown value")],
)
def test_other_breach_actions_refuse(action, meaning) -> None:
    report = findings(GF_ACTION=action)
    assert not report.consistent
    assert any(f"GF_ACTION = {action} ({meaning})" in r for r in report.refusals), report.refusals


def test_fully_disabled_geofence_reports_every_reason() -> None:
    report = findings(GF_MAX_HOR_DIST=0.0, GF_MAX_VER_DIST=0.0, GF_ACTION=0)
    assert len(report.refusals) == 3


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("GF_MAX_HOR_DIST", -1.0),
        ("GF_MAX_VER_DIST", math.nan),
        ("MPC_XY_VEL_MAX", 0.0),
        ("MPC_XY_VEL_MAX", math.inf),
        ("BAT_LOW_THR", 0.0),
        ("BAT_LOW_THR", 15.0),  # percent instead of fraction must not pass
        ("BAT_LOW_THR", True),
        ("GF_ACTION", 2.0),
        ("GF_ACTION", None),
        ("RTL_RETURN_ALT", -1.0),
        ("RTL_RETURN_ALT", math.nan),
        ("RTL_RETURN_ALT", "20"),
        ("RTL_RETURN_ALT", False),
    ],
)
def test_malformed_px4_values_refuse(name, bad) -> None:
    report = findings(**{name: bad})
    assert not report.consistent
    assert any(name in r for r in report.refusals), report.refusals


@pytest.mark.parametrize("name", sorted(PX4_LIMIT_PARAMS))
def test_missing_parameter_refuses(name) -> None:
    values = dict(ENFORCED)
    del values[name]
    report = px4_limit_findings(values, MISSION, PREFLIGHT)
    assert any(name in r for r in report.refusals)


def test_documented_px4_defaults_refuse_until_a_geofence_is_set() -> None:
    report = px4_limit_findings(PX4_DEFAULTS, X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS)
    assert not report.consistent
    assert len(report.refusals) == 2  # horizontal and vertical geofence disabled


def test_x500_sitl_settings_pass_with_the_checklist_geofence() -> None:
    # Values from simulation/mavsdk/SITL_SESSION_CHECKLIST.md (simulator settings).
    sitl = {
        **PX4_DEFAULTS,
        "GF_MAX_HOR_DIST": 150.0,
        "GF_MAX_VER_DIST": 40.0,
        "GF_ACTION": 3,
        "RTL_RETURN_ALT": 20.0,
    }
    report = px4_limit_findings(sitl, X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS)
    assert report.consistent, report.refusals


# --- PX4 RTL altitude vs PX4 vertical geofence ---------------------------------


def test_rtl_return_altitude_above_vertical_geofence_refuses() -> None:
    # The flight script ends every mission with a PX4 RTL request; PX4 climbs to
    # RTL_RETURN_ALT first, so a higher value flies into PX4's own fence.
    report = findings(RTL_RETURN_ALT=45.0)
    assert report.refusals == (
        "PX4 RTL_RETURN_ALT 45 m is above PX4 GF_MAX_VER_DIST 40 m: "
        "PX4's return would climb into its own vertical geofence",
    )


@pytest.mark.parametrize("rtl_alt", [0.0, 20.0, 35.0, 40.0])
def test_rtl_return_altitude_at_or_below_vertical_geofence_passes(rtl_alt) -> None:
    # 35 m is above the 30 m companion ceiling: not compared (open owner question).
    assert findings(RTL_RETURN_ALT=rtl_alt).consistent


def test_checklist_geofence_with_px4_default_rtl_altitude_refuses() -> None:
    # Checklist fence (40 m) but RTL_RETURN_ALT left at the PX4 default 60 m.
    sitl = {**PX4_DEFAULTS, "GF_MAX_HOR_DIST": 150.0, "GF_MAX_VER_DIST": 40.0, "GF_ACTION": 3}
    report = px4_limit_findings(sitl, X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS)
    assert len(report.refusals) == 1
    assert "RTL_RETURN_ALT 60 m is above PX4 GF_MAX_VER_DIST 40 m" in report.refusals[0]


@pytest.mark.parametrize("fence", [0.0, -5.0, math.nan, "unreadable"])
def test_disabled_or_invalid_fence_is_one_refusal_not_two(fence) -> None:
    # The geofence check already refuses; the RTL comparison adds nothing.
    report = findings(GF_MAX_VER_DIST=fence, RTL_RETURN_ALT=60.0)
    assert len(report.refusals) == 1
    assert "GF_MAX_VER_DIST" in report.refusals[0]
    assert "RTL_RETURN_ALT" not in report.refusals[0]


def test_companion_ceiling_contradiction_and_rtl_contradiction_reported_together() -> None:
    report = findings(GF_MAX_VER_DIST=25.0, RTL_RETURN_ALT=30.0)
    text = "; ".join(report.refusals)
    assert len(report.refusals) == 2
    assert "ceiling 30 m is looser than PX4 GF_MAX_VER_DIST 25 m" in text
    assert "RTL_RETURN_ALT 30 m is above PX4 GF_MAX_VER_DIST 25 m" in text


def test_invalid_companion_limits_raise_before_comparing() -> None:
    bad = PreflightLimits(min_battery_fraction=0.0, max_telemetry_age_s=2.0)
    with pytest.raises(ValueError):
        px4_limit_findings(ENFORCED, MISSION, bad)


# --- reading from MAVSDK ------------------------------------------------------


class FakeParams:
    def __init__(self, values, hang=(), fail=()):
        self.values, self.hang, self.fail = dict(values), set(hang), set(fail)
        self.calls = []

    async def _get(self, kind, name):
        self.calls.append((kind, name))
        if name in self.hang:
            await asyncio.sleep(10)
        if name in self.fail:
            raise RuntimeError("PARAM_NAME_DOES_NOT_EXIST")
        return self.values[name]

    async def get_param_float(self, name):
        return await self._get("float", name)

    async def get_param_int(self, name):
        return await self._get("int", name)

    def vehicle(self):
        # Only a param plugin: any attempt to send a command would fail loudly.
        return SimpleNamespace(param=self)


def test_reader_uses_the_typed_getter_for_each_parameter() -> None:
    params = FakeParams(ENFORCED)
    values = asyncio.run(read_px4_limit_params(params.vehicle(), 1.0))
    assert values == ENFORCED
    assert dict((n, k) for k, n in params.calls) == PX4_LIMIT_PARAMS


def test_failed_and_slow_reads_become_refusals_not_passes() -> None:
    params = FakeParams(ENFORCED, hang={"GF_MAX_VER_DIST"}, fail={"BAT_LOW_THR"})
    with pytest.raises(Px4LimitsRefused) as info:
        asyncio.run(require_px4_limits_consistent(params.vehicle(), MISSION, PREFLIGHT, 0.05))
    text = str(info.value)
    assert "GF_MAX_VER_DIST not read as a number: no reply within 0.05 s" in text
    assert "BAT_LOW_THR not read as a number: read failed (RuntimeError" in text


def test_consistent_vehicle_returns_report() -> None:
    params = FakeParams(ENFORCED)
    report = asyncio.run(require_px4_limits_consistent(params.vehicle(), MISSION, PREFLIGHT, 1.0))
    assert report.consistent


def test_vehicle_with_px4_default_geofence_is_refused() -> None:
    params = FakeParams(PX4_DEFAULTS)
    with pytest.raises(Px4LimitsRefused, match="GF_MAX_HOR_DIST = 0"):
        asyncio.run(require_px4_limits_consistent(params.vehicle(), MISSION, PREFLIGHT, 1.0))
