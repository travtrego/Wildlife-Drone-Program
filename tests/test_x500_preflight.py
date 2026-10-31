"""Unit tests for the companion-side preflight gate (no vehicle, no MAVSDK)."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from x500.flight.preflight import (
    REQUIRED_HEALTH_FLAGS,
    PreflightLimits,
    PreflightRefused,
    PreflightSample,
    battery_fraction_from_percent,
    preflight_refusals,
    read_preflight_sample,
    require_preflight_ready,
)
from x500.flight.settings import X500_SITL_PREFLIGHT_LIMITS

LIMITS = PreflightLimits(min_battery_fraction=0.6, max_telemetry_age_s=2.0)
ALL_OK = {flag: True for flag in REQUIRED_HEALTH_FLAGS}


def sample(**overrides) -> PreflightSample:
    fields = dict(
        armed=False, in_air=False, battery_fraction=0.9, health=dict(ALL_OK), oldest_at_s=10.0
    )
    fields.update(overrides)
    return PreflightSample(**fields)


def test_ready_vehicle_has_no_refusals() -> None:
    assert preflight_refusals(sample(), 10.5, LIMITS) == ()


def test_no_sample_is_refused() -> None:
    assert preflight_refusals(None, 10.0, LIMITS) == ("no preflight telemetry received",)


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"armed": True}, "vehicle is already armed"),
        ({"armed": None}, "armed state unknown"),
        ({"armed": 0}, "armed state unknown"),  # non-bool is not "disarmed"
        ({"in_air": True}, "vehicle is in the air"),
        ({"in_air": "false"}, "in-air state unknown"),
        ({"battery_fraction": None}, "battery level unknown"),
        ({"battery_fraction": 0.59}, "battery 59% below companion minimum 60%"),
    ],
)
def test_vehicle_state_refusals(overrides, expected) -> None:
    assert expected in preflight_refusals(sample(**overrides), 10.0, LIMITS)


def test_battery_exactly_at_minimum_passes() -> None:
    assert preflight_refusals(sample(battery_fraction=0.6), 10.0, LIMITS) == ()


@pytest.mark.parametrize("flag", REQUIRED_HEALTH_FLAGS)
def test_each_false_health_flag_refuses(flag) -> None:
    health = dict(ALL_OK, **{flag: False})
    assert preflight_refusals(sample(health=health), 10.0, LIMITS) == (
        f"PX4 health {flag} is False",
    )


def test_missing_or_non_bool_health_flag_is_unknown() -> None:
    health = dict(ALL_OK)
    del health["is_armable"]
    health["is_home_position_ok"] = 1
    reasons = preflight_refusals(sample(health=health), 10.0, LIMITS)
    assert "PX4 health is_armable is unknown" in reasons
    assert "PX4 health is_home_position_ok is unknown" in reasons


@pytest.mark.parametrize(
    "taken_at, now, expected",
    [
        (10.0, 12.5, "telemetry is 2.5 s old"),
        (10.0, 9.0, "telemetry timestamp is in the future"),
        (math.nan, 10.0, "telemetry timestamp is not finite"),
    ],
)
def test_timing_refusals(taken_at, now, expected) -> None:
    reasons = preflight_refusals(sample(oldest_at_s=taken_at), now, LIMITS)
    assert any(r.startswith(expected) for r in reasons)


def test_all_reasons_are_reported_together() -> None:
    bad = sample(armed=True, in_air=True, battery_fraction=None, oldest_at_s=0.0)
    assert len(preflight_refusals(bad, 10.0, LIMITS)) == 4


@pytest.mark.parametrize(
    "limits",
    [
        PreflightLimits(0.0, 2.0),
        PreflightLimits(1.1, 2.0),
        PreflightLimits(math.nan, 2.0),
        PreflightLimits(0.5, 0.0),
        PreflightLimits(0.5, math.inf),
    ],
)
def test_invalid_limits_raise(limits) -> None:
    with pytest.raises(ValueError):
        preflight_refusals(sample(), 10.0, limits)


def test_x500_placeholder_limits_are_valid() -> None:
    X500_SITL_PREFLIGHT_LIMITS.validate()


@pytest.mark.parametrize(
    "raw, expected",
    [
        (100.0, 1.0),
        (55, 0.55),
        (0.0, 0.0),
        (101.0, None),
        (-1.0, None),
        (math.nan, None),
        (True, None),
        ("90", None),
        (None, None),
    ],
)
def test_battery_percent_conversion(raw, expected) -> None:
    assert battery_fraction_from_percent(raw) == expected


# --- reading from a MAVSDK-like object ----------------------------------------


def _stream(*values):
    def factory():
        async def gen():
            for value in values:
                yield value

        return gen()

    return factory


def _silent():
    def factory():
        async def gen():
            await asyncio.sleep(10)
            yield None

        return gen()

    return factory


def fake_drone(armed=False, in_air=False, percent=80.0, health=None, **replace):
    streams = dict(
        armed=_stream(armed),
        in_air=_stream(in_air),
        battery=_stream(SimpleNamespace(remaining_percent=percent)),
        health=_stream(SimpleNamespace(**(health or ALL_OK))),
    )
    streams.update(replace)
    return SimpleNamespace(telemetry=SimpleNamespace(**streams))


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        self.t += 0.01
        return self.t


def test_reader_builds_sample_with_oldest_time_and_converted_battery() -> None:
    s = asyncio.run(read_preflight_sample(fake_drone(percent=80.0), 1.0, Clock()))
    assert s.armed is False and s.in_air is False
    assert s.battery_fraction == pytest.approx(0.8)
    assert s.health == ALL_OK
    assert s.oldest_at_s == pytest.approx(100.01)


def test_reader_marks_missing_health_attributes_unknown() -> None:
    partial = SimpleNamespace(is_global_position_ok=True)
    drone = fake_drone()
    drone.telemetry.health = _stream(partial)
    s = asyncio.run(read_preflight_sample(drone, 1.0, Clock()))
    assert s.health["is_armable"] is None
    assert "PX4 health is_armable is unknown" in preflight_refusals(s, s.oldest_at_s, LIMITS)


def test_reader_times_out_on_silent_stream() -> None:
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(read_preflight_sample(fake_drone(battery=_silent()), 0.05, Clock()))


def test_reader_raises_when_stream_ends_empty() -> None:
    with pytest.raises(RuntimeError, match="battery telemetry stream ended"):
        asyncio.run(read_preflight_sample(fake_drone(battery=_stream()), 1.0, Clock()))


def test_require_ready_raises_with_reasons() -> None:
    with pytest.raises(PreflightRefused) as info:
        asyncio.run(require_preflight_ready(fake_drone(armed=True), LIMITS, 1.0, Clock()))
    assert info.value.reasons == ("vehicle is already armed",)


def test_require_ready_returns_sample_when_ready() -> None:
    s = asyncio.run(require_preflight_ready(fake_drone(), LIMITS, 1.0, Clock()))
    assert s.armed is False
