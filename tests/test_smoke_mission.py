import asyncio
from types import SimpleNamespace

import pytest

from simulation.mavsdk.smoke_mission import (
    _wait_for_takeoff_altitude,
    _wait_until_in_air,
    _wait_until_landed,
)


def stream(*values):
    async def generate():
        for value in values:
            yield value

    return generate


def test_takeoff_waits_for_airborne_state() -> None:
    drone = SimpleNamespace(telemetry=SimpleNamespace(in_air=stream(False, True)))
    asyncio.run(_wait_until_in_air(drone))


def test_takeoff_does_not_pass_when_stream_ends_on_ground() -> None:
    drone = SimpleNamespace(telemetry=SimpleNamespace(in_air=stream(False)))
    with pytest.raises(RuntimeError, match="before takeoff"):
        asyncio.run(_wait_until_in_air(drone))


def test_altitude_gate_waits_for_ninety_percent_of_target() -> None:
    positions = [SimpleNamespace(relative_altitude_m=value) for value in (0.0, 2.6, 2.8)]
    drone = SimpleNamespace(telemetry=SimpleNamespace(position=stream(*positions)))
    assert asyncio.run(_wait_for_takeoff_altitude(drone, 3.0)) == 2.8


def test_altitude_gate_rejects_ended_stream() -> None:
    drone = SimpleNamespace(
        telemetry=SimpleNamespace(position=stream(SimpleNamespace(relative_altitude_m=1.0)))
    )
    with pytest.raises(RuntimeError, match="before takeoff altitude"):
        asyncio.run(_wait_for_takeoff_altitude(drone, 3.0))


def test_altitude_gate_times_out_without_telemetry() -> None:
    async def no_positions():
        await asyncio.Event().wait()
        yield  # pragma: no cover

    drone = SimpleNamespace(telemetry=SimpleNamespace(position=no_positions))
    with pytest.raises(TimeoutError):
        asyncio.run(_wait_for_takeoff_altitude(drone, 3.0, timeout_s=0.01))


def test_landing_waits_for_on_ground_state() -> None:
    drone = SimpleNamespace(telemetry=SimpleNamespace(in_air=stream(True, False)))
    asyncio.run(_wait_until_landed(drone))


def test_landing_does_not_pass_when_stream_ends_in_air() -> None:
    drone = SimpleNamespace(telemetry=SimpleNamespace(in_air=stream(True)))
    with pytest.raises(RuntimeError, match="before landing"):
        asyncio.run(_wait_until_landed(drone))
