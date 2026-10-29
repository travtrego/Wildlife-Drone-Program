"""Tests for feeding MAVSDK-style telemetry into the X500 mission monitor.

Everything here uses plain values, fake clocks and a fake in-memory vehicle.
None of it is evidence that PX4 SITL behaves this way.
"""

from __future__ import annotations

import asyncio
import math
from enum import Enum
from types import SimpleNamespace

import pytest

from shared.autonomy.sitl import SitlMissionConfig
from simulation.mavsdk.waypoint_mission_flight import fly_waypoint_mission, run_flight
from x500.flight.mission_monitor import (
    EndReason,
    MissionExecutionMonitor,
    MissionSample,
    MissionState,
    MissionStatus,
    MonitorSettings,
    Recommendation,
)
from x500.flight.mission_telemetry import (
    MissionStream,
    MissionTelemetryCombiner,
    follow_up_request,
    run_monitor,
    subscribe_mission_telemetry,
)
from x500.flight.waypoint_mission import (
    LocalWaypoint,
    MissionCheckError,
    MultirotorMissionLimits,
)

N = 3


class Mode(Enum):  # stand-in for mavsdk.telemetry.FlightMode
    HOLD = 1
    MISSION = 2
    RETURN_TO_LAUNCH = 3
    POSCTL = 4


def settings(**overrides) -> MonitorSettings:
    values = dict(
        expected_item_count=N,
        start_timeout_s=5.0,
        max_item_time_s=20.0,
        max_mission_time_s=60.0,
        max_telemetry_age_s=1.0,
    )
    values.update(overrides)
    return MonitorSettings(**values)


def feed(c: MissionTelemetryCombiner, t, mode="MISSION", armed=True, in_air=True, current=0):
    c.update_flight_mode(mode, t)
    c.update_armed(armed, t)
    c.update_in_air(in_air, t)
    c.update_progress(current, N, t)


# --- combiner ------------------------------------------------------------------


def test_no_sample_until_every_stream_reported() -> None:
    c = MissionTelemetryCombiner()
    c.update_flight_mode("MISSION", 1.0)
    c.update_armed(True, 1.0)
    c.update_in_air(True, 1.0)
    assert c.sample() is None
    assert c.missing_streams() == (MissionStream.PROGRESS,)
    c.update_progress(0, N, 1.0)
    assert c.sample() == MissionSample(1.0, "MISSION", True, True, 0, N)


def test_sample_age_is_oldest_periodic_stream() -> None:
    c = MissionTelemetryCombiner()
    feed(c, 1.0)
    c.update_flight_mode("MISSION", 5.0)
    c.update_armed(True, 5.0)  # in_air stays at 1.0
    assert c.sample().time_s == 1.0


def test_progress_reported_only_on_change_does_not_age_sample() -> None:
    c = MissionTelemetryCombiner()
    feed(c, 1.0)
    c.update_flight_mode("MISSION", 9.0)
    c.update_armed(True, 9.0)
    c.update_in_air(True, 9.0)
    sample = c.sample()
    assert sample.time_s == 9.0 and sample.current_item == 0


def test_out_of_order_update_is_dropped() -> None:
    c = MissionTelemetryCombiner()
    feed(c, 2.0, current=1)
    c.update_progress(0, N, 1.5)
    c.update_flight_mode("POSCTL", 1.0)
    sample = c.sample()
    assert sample.current_item == 1 and sample.flight_mode == "MISSION"


@pytest.mark.parametrize("bad", [math.nan, math.inf, None, True])
def test_non_finite_timestamp_raises(bad) -> None:
    with pytest.raises(ValueError):
        MissionTelemetryCombiner().update_armed(True, bad)


# --- run_monitor with a fake clock ---------------------------------------------


class FakeTime:
    def __init__(self, script=None):
        self.now = 0.0
        self.script = script or (lambda t: None)

    def clock(self):
        return self.now

    async def sleep(self, dt):
        self.now = round(self.now + dt, 6)
        self.script(self.now)


def _run(monitor, combiner, ft, started_at=0.0, interval=0.5):
    return asyncio.run(
        run_monitor(monitor, combiner, started_at, ft.clock, interval, sleep=ft.sleep)
    )


def test_run_monitor_reaches_completion() -> None:
    c = MissionTelemetryCombiner()

    def script(t):
        item = min(int(t), N)
        feed(c, t, current=item)

    ft = FakeTime(script)
    m = MissionExecutionMonitor(settings())
    m.start(0.0)
    status = _run(m, c, ft)
    assert status.state is MissionState.COMPLETED
    assert ft.now == 3.0


def test_pre_start_samples_are_not_fed() -> None:
    c = MissionTelemetryCombiner()
    # Before the start request the vehicle was on the ground in a pilot mode.
    feed(c, 9.0, mode="POSCTL", armed=False, in_air=False)

    def script(t):
        if t >= 10.5:
            feed(c, t, current=min(int(t - 10), N))

    ft = FakeTime(script)
    ft.now = 10.0
    m = MissionExecutionMonitor(settings())
    m.start(10.0)
    status = _run(m, c, ft, started_at=10.0)
    assert status.state is MissionState.COMPLETED  # not PILOT_TAKEOVER from t=9


def test_one_silent_periodic_stream_ends_as_stale() -> None:
    c = MissionTelemetryCombiner()

    def script(t):
        c.update_flight_mode("MISSION", t)
        c.update_armed(True, t)
        c.update_progress(0, N, t)
        # in_air stopped after t=1.0

    feed(c, 0.0)
    c.update_in_air(True, 1.0)
    ft = FakeTime(script)
    m = MissionExecutionMonitor(settings())
    m.start(0.0)
    status = _run(m, c, ft)
    assert status.reason is EndReason.TELEMETRY_STALE
    assert status.recommendation is Recommendation.NONE


def test_missing_progress_times_out_without_guessing() -> None:
    c = MissionTelemetryCombiner()

    def script(t):
        c.update_flight_mode("MISSION", t)
        c.update_armed(True, t)
        c.update_in_air(True, t)

    ft = FakeTime(script)
    m = MissionExecutionMonitor(settings(max_telemetry_age_s=10.0))
    m.start(0.0)
    assert _run(m, c, ft).reason is EndReason.START_TIMEOUT


def test_pilot_takeover_mid_mission_ends_attempt() -> None:
    c = MissionTelemetryCombiner()

    def script(t):
        feed(c, t, mode="POSCTL" if t >= 2.0 else "MISSION", current=1)

    ft = FakeTime(script)
    m = MissionExecutionMonitor(settings())
    m.start(0.0)
    assert _run(m, c, ft).reason is EndReason.PILOT_TAKEOVER


def test_run_monitor_rejects_bad_interval() -> None:
    m = MissionExecutionMonitor(settings())
    m.start(0.0)
    with pytest.raises(ValueError):
        _run(m, MissionTelemetryCombiner(), FakeTime(), interval=0.0)


# --- subscriptions ---------------------------------------------------------------


def _gen(*values, error=None):
    async def generate():
        for value in values:
            yield value
        if error:
            raise error

    return generate


def test_subscriptions_fill_combiner_and_record_stream_end() -> None:
    drone = SimpleNamespace(
        telemetry=SimpleNamespace(
            flight_mode=_gen(Mode.MISSION),
            armed=_gen(True),
            in_air=_gen(True, error=RuntimeError("link lost")),
        ),
        mission=SimpleNamespace(mission_progress=_gen(SimpleNamespace(current=1, total=N))),
    )
    c = MissionTelemetryCombiner()

    async def go():
        tasks = subscribe_mission_telemetry(drone, c, lambda: 4.0)
        await asyncio.gather(*tasks)

    asyncio.run(go())
    assert c.sample() == MissionSample(4.0, Mode.MISSION, True, True, 1, N)
    assert c.stream_errors[MissionStream.IN_AIR] == "RuntimeError: link lost"
    assert c.stream_errors[MissionStream.ARMED] == "stream ended"


# --- follow-up decision ----------------------------------------------------------

COMPLETED = MissionStatus(MissionState.COMPLETED, current_item=N, total_items=N)


def ended(reason, recommendation=Recommendation.NONE):
    return MissionStatus(MissionState.ENDED, reason=reason, recommendation=recommendation)


def latest(mode="MISSION", t=10.0, armed=True, in_air=True):
    return MissionSample(t, mode, armed, in_air, N, N)


def test_completed_mission_requests_rtl_with_fresh_state() -> None:
    assert follow_up_request(COMPLETED, latest(), 10.5, 1.0).request_return_to_launch


def test_stalled_item_requests_rtl_only_while_still_in_mission() -> None:
    stalled = ended(EndReason.ITEM_STALLED, Recommendation.RETURN_TO_LAUNCH)
    assert follow_up_request(stalled, latest(), 10.0, 1.0).request_return_to_launch
    assert not follow_up_request(stalled, latest("POSCTL"), 10.0, 1.0).request_return_to_launch


@pytest.mark.parametrize(
    "status, sample, now",
    [
        (COMPLETED, latest(), 12.0),  # stale
        (COMPLETED, latest(), 9.0),  # sample from the future
        (COMPLETED, None, 10.0),
        (COMPLETED, latest(Mode.POSCTL), 10.0),
        (COMPLETED, latest("RETURN_TO_LAUNCH"), 10.0),
        (COMPLETED, latest("LAND"), 10.0),
        (COMPLETED, latest("OFFBOARD"), 10.0),
        (COMPLETED, latest(in_air=False), 10.0),
        (COMPLETED, latest(armed=False), 10.0),
        (COMPLETED, latest(armed="yes"), 10.0),
        (ended(EndReason.PILOT_TAKEOVER), latest(), 10.0),
        (ended(EndReason.PX4_RECOVERY_MODE), latest(), 10.0),
        (ended(EndReason.TELEMETRY_STALE), latest(), 10.0),
        (ended(EndReason.MODE_CHANGED), latest(), 10.0),
        (MissionStatus(MissionState.IN_PROGRESS), latest(), 10.0),
    ],
)
def test_no_rtl_request_when_pilot_or_px4_owns_vehicle(status, sample, now) -> None:
    assert not follow_up_request(status, sample, now, 1.0).request_return_to_launch


# --- SITL entry point against a fake vehicle --------------------------------------

LIMITS = MultirotorMissionLimits(30.0, 3.0, 100.0, 5.0, 5)
SQUARE = [
    LocalWaypoint(20.0, 0.0, 10.0, 3.0),
    LocalWaypoint(20.0, 20.0, 10.0, 3.0),
    LocalWaypoint(0.0, 0.0, 10.0, 3.0, False),
]


class _Item:
    class CameraAction:
        NONE = "none"

    class VehicleAction:
        NONE = "none"

    def __init__(self, **fields):
        self.__dict__.update(fields)


MISSION_MODULE = SimpleNamespace(
    MissionItem=_Item, MissionPlan=lambda items: SimpleNamespace(mission_items=items)
)


class FakeVehicle:
    """In-memory vehicle: progresses through items after start, lands after RTL."""

    def __init__(self, stall=False):
        self.mode, self.armed, self.in_air = Mode.HOLD, False, False
        self.current, self.plan, self.stall = 0, None, stall
        self.commands = []
        ok = SimpleNamespace(is_global_position_ok=True, is_home_position_ok=True)
        self.telemetry = SimpleNamespace(
            health=_gen(ok),
            home=_gen(SimpleNamespace(latitude_deg=41.6, longitude_deg=-71.2)),
            flight_mode=self._periodic(lambda: self.mode),
            armed=self._periodic(lambda: self.armed),
            in_air=self._periodic(lambda: self.in_air),
        )
        self.mission = SimpleNamespace(
            upload_mission=self._upload,
            download_mission=self._download,
            start_mission=self._start,
            mission_progress=self._progress,
        )
        self.action = SimpleNamespace(arm=self._arm, return_to_launch=self._rtl)

    def _periodic(self, read):
        async def gen():
            while True:
                yield read()
                await asyncio.sleep(0.005)

        return gen

    async def _progress(self):
        last = None
        while True:
            if self.plan is not None and self.current != last:
                last = self.current
                yield SimpleNamespace(current=self.current, total=len(self.plan.mission_items))
            await asyncio.sleep(0.005)

    async def _upload(self, plan):
        self.plan = plan

    async def _download(self):
        return self.plan

    async def _arm(self):
        self.commands.append("arm")
        self.armed = True

    async def _start(self):
        self.commands.append("start_mission")

        async def fly():
            self.mode, self.in_air = Mode.MISSION, True
            for _ in self.plan.mission_items:
                await asyncio.sleep(0.03)
                if not self.stall:
                    self.current += 1

        self._flight = asyncio.get_running_loop().create_task(fly())

    async def _rtl(self):
        self.commands.append("return_to_launch")
        self.mode = Mode.RETURN_TO_LAUNCH

        async def land():
            await asyncio.sleep(0.03)
            self.in_air = False

        self._landing = asyncio.get_running_loop().create_task(land())


def _fly(vehicle, **overrides):
    return asyncio.run(
        fly_waypoint_mission(
            vehicle,
            SQUARE,
            LIMITS,
            MISSION_MODULE,
            health_timeout_s=1.0,
            settings_for=lambda n: settings(expected_item_count=n, **overrides),
            check_interval_s=0.01,
            landing_timeout_s=1.0,
        )
    )


def test_fake_flight_completes_requests_rtl_and_lands() -> None:
    vehicle = FakeVehicle()
    result = _fly(vehicle)
    assert result.status.state is MissionState.COMPLETED
    assert result.passed and result.landed
    assert vehicle.commands == ["arm", "start_mission", "return_to_launch"]


def test_fake_flight_stall_requests_rtl_but_does_not_pass() -> None:
    vehicle = FakeVehicle(stall=True)
    result = _fly(vehicle, max_item_time_s=0.1, max_mission_time_s=5.0)
    assert result.status.reason is EndReason.ITEM_STALLED
    assert result.rtl_requested and not result.passed
    assert vehicle.commands[-1] == "return_to_launch"


def test_fake_flight_pilot_takeover_sends_no_follow_up() -> None:
    vehicle = FakeVehicle()
    original_start = vehicle.mission.start_mission

    async def start_then_takeover():
        await original_start()

        async def takeover():
            await asyncio.sleep(0.04)
            vehicle.mode = Mode.POSCTL

        vehicle._takeover = asyncio.get_running_loop().create_task(takeover())

    vehicle.mission.start_mission = start_then_takeover
    result = _fly(vehicle)
    assert result.status.reason is EndReason.PILOT_TAKEOVER
    assert vehicle.commands == ["arm", "start_mission"]
    assert not result.passed


@pytest.mark.parametrize(
    "address",
    ["udpin://0.0.0.0:14540", "udpin://192.168.1.20:14540", "serial:///dev/ttyACM0:57600"],
)
def test_entry_point_refuses_non_sitl_endpoint_before_connecting(address) -> None:
    with pytest.raises(ValueError, match="simulation-only"):
        asyncio.run(run_flight(SitlMissionConfig(system_address=address), SQUARE, LIMITS))


def test_entry_point_refuses_out_of_limit_mission_before_connecting() -> None:
    far = [LocalWaypoint(500.0, 0.0, 10.0, 3.0)]
    with pytest.raises(MissionCheckError):
        asyncio.run(run_flight(SitlMissionConfig(), far, LIMITS))


def test_follow_up_reason_names_pilot_and_px4_modes() -> None:
    assert "pilot mode POSCTL" in follow_up_request(COMPLETED, latest("POSCTL"), 10.0, 1.0).reason
    assert "already in LAND" in follow_up_request(COMPLETED, latest("LAND"), 10.0, 1.0).reason
