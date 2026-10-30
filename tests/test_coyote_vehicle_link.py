"""Unit tests for the Coyote MAVSDK telemetry pumps and R6 delegation watch.

Fake vehicles and clocks only. Nothing here proves PX4 SITL behaviour.
"""

import asyncio
import math
from dataclasses import dataclass
from enum import Enum

import pytest

from coyote.autonomy.delegation import DelegationAuthority, GrantCommand
from coyote.autonomy.ground_alerts import (
    AlertSeverity,
    GroundAlertOutbox,
    OutboxConfig,
    StatusMessage,
)
from coyote.autonomy.telemetry import Stream, TelemetryTracker, observe_vehicle
from coyote.autonomy.vehicle_link import (
    WatchConfig,
    mavsdk_status_text_sender,
    run_delegation_watch,
    subscribe_vehicle_telemetry,
    watch_step,
)


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeFlightMode(Enum):
    HOLD = 3
    RETURN_TO_LAUNCH = 5


@dataclass
class FakePosition:
    relative_altitude_m: float


@dataclass
class FakeBattery:
    remaining_percent: float


def feed(
    tracker: TelemetryTracker, t: float, *, mode="HOLD", armed=True, in_air=False, failsafe=False
) -> None:
    tracker.update_flight_mode(mode, t)
    tracker.update_armed(armed, t)
    tracker.update_in_air(in_air, t)
    tracker.update_position(0.0, t)
    tracker.update_battery_percent(95.0, t)
    tracker.update_failsafe(failsafe, t)  # stand-in: the real source is not chosen


class Sender:
    """Async sender that can succeed, fail, raise or hang."""

    def __init__(self, behaviour: str = "ok") -> None:
        self.behaviour = behaviour
        self.sent: list[StatusMessage] = []
        self.attempts = 0

    async def __call__(self, message: StatusMessage) -> object:
        self.attempts += 1
        if self.behaviour == "raise":
            raise ConnectionError("link down")
        if self.behaviour == "false":
            return False
        if self.behaviour == "hang":
            await asyncio.sleep(10.0)
        self.sent.append(message)
        return True


def delegated_setup(clock: Clock):
    tracker, authority = TelemetryTracker(), DelegationAuthority()
    feed(tracker, clock.t)
    observe_vehicle(tracker, authority, clock.t)
    assert authority.request_grant(GrantCommand(1, clock.t), clock.t).accepted
    return tracker, authority, GroundAlertOutbox()


def step(tracker, authority, outbox, sender, clock, config=None):
    return asyncio.run(watch_step(tracker, authority, outbox, sender, clock, config))


# ------------------------------------------------------------- watch step
def test_silent_link_revokes_and_alerts_without_any_companion_request() -> None:
    clock = Clock(100.0)
    tracker, authority, outbox = delegated_setup(clock)
    sender = Sender()

    tick = step(tracker, authority, outbox, sender, clock)
    assert tick.delegated and tick.sent is None

    clock.t += 1.5  # every stream silent longer than the 1 s placeholder
    tick = step(tracker, authority, outbox, sender, clock)
    assert not tick.delegated
    assert [m.text for m in sender.sent] == ["COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST"]
    assert tick.pending_alerts == 0


def test_px4_recovery_mode_revokes_with_its_own_reason() -> None:
    clock = Clock(5.0)
    tracker, authority, outbox = delegated_setup(clock)
    sender = Sender()
    clock.t += 0.1
    feed(tracker, clock.t, mode=FakeFlightMode.RETURN_TO_LAUNCH, in_air=True)
    tick = step(tracker, authority, outbox, sender, clock)
    assert not tick.delegated
    assert sender.sent[0].text.endswith("PX4 RTL/LAND")


def test_failed_send_keeps_alert_and_respects_retry_spacing() -> None:
    clock = Clock(0.0)
    tracker, authority, outbox = delegated_setup(clock)
    sender = Sender("raise")
    clock.t = 2.0
    tick = step(tracker, authority, outbox, sender, clock)
    assert not tick.delegated and tick.send_failed and tick.pending_alerts == 1

    clock.t += 0.1  # inside the 0.5 s retry placeholder: no new attempt
    tick = step(tracker, authority, outbox, sender, clock)
    assert sender.attempts == 1 and not tick.send_failed

    sender.behaviour = "ok"
    clock.t += 0.5
    tick = step(tracker, authority, outbox, sender, clock)
    assert tick.sent is not None and tick.pending_alerts == 0
    assert outbox.pending() == ()


@pytest.mark.parametrize("behaviour", ["false", "hang"])
def test_non_true_result_or_timeout_is_a_failed_send(behaviour: str) -> None:
    clock = Clock(0.0)
    tracker, authority, outbox = delegated_setup(clock)
    authority.revoke_by_operator(0.0)
    tick = step(
        tracker,
        authority,
        outbox,
        Sender(behaviour),
        clock,
        WatchConfig(send_timeout_s=0.01),
    )
    assert tick.send_failed and tick.pending_alerts == 1


def test_delivery_never_restores_delegation() -> None:
    clock = Clock(0.0)
    tracker, authority, outbox = delegated_setup(clock)
    authority.revoke_by_operator(0.0)
    sender = Sender()
    for _ in range(3):
        clock.t += 0.2
        feed(tracker, clock.t)
        tick = step(tracker, authority, outbox, sender, clock)
        assert not tick.delegated
    assert len(sender.sent) == 1


def test_without_failsafe_source_no_grant_is_possible() -> None:
    """Conservative default while the failsafe signal is unchosen."""

    clock = Clock(0.0)
    tracker, authority = TelemetryTracker(), DelegationAuthority()
    tracker.update_flight_mode("HOLD", 0.0)
    tracker.update_armed(True, 0.0)
    tracker.update_in_air(False, 0.0)
    tracker.update_position(0.0, 0.0)
    tracker.update_battery_percent(90.0, 0.0)
    step(tracker, authority, GroundAlertOutbox(OutboxConfig()), Sender(), clock)
    assert not authority.request_grant(GrantCommand(1, 0.0), 0.0).accepted


@pytest.mark.parametrize(
    "kwargs", [{"tick_interval_s": 0.0}, {"send_timeout_s": math.inf}, {"tick_interval_s": True}]
)
def test_invalid_watch_config_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        WatchConfig(**kwargs).validate()


def test_run_loop_ticks_until_cancelled() -> None:
    clock = Clock(0.0)
    tracker, authority, outbox = delegated_setup(clock)
    ticks = []

    async def fake_sleep(interval: float) -> None:
        clock.t += interval
        if len(ticks) >= 10:
            raise asyncio.CancelledError

    async def go() -> None:
        with pytest.raises(asyncio.CancelledError):
            await run_delegation_watch(
                tracker,
                authority,
                outbox,
                Sender(),
                clock,
                sleep=fake_sleep,
                on_tick=ticks.append,
            )

    asyncio.run(go())
    # 0.2 s ticks, no new telemetry: revoked once the 1 s limit is exceeded.
    assert ticks[0].delegated and not ticks[-1].delegated
    assert sum(t.sent is not None for t in ticks) == 1


# ---------------------------------------------------------- telemetry pumps
class FakeTelemetry:
    def __init__(self, values: dict[str, list], fail: set[str] = frozenset()) -> None:
        self._values, self._fail = values, fail

    def _gen(self, name: str):
        async def gen():
            for v in self._values.get(name, []):
                yield v
                await asyncio.sleep(0)
            if name in self._fail:
                raise RuntimeError(f"{name} broke")

        return gen

    def __getattr__(self, name: str):
        return self._gen(name)


class FakeDrone:
    def __init__(self, telemetry: FakeTelemetry) -> None:
        self.telemetry = telemetry


def run_pumps(drone: FakeDrone, clock: Clock) -> tuple[TelemetryTracker, dict]:
    tracker, errors = TelemetryTracker(), {}

    async def go() -> None:
        await asyncio.gather(*subscribe_vehicle_telemetry(drone, tracker, clock, errors))

    asyncio.run(go())
    return tracker, errors


def test_pumps_feed_every_stream_and_convert_battery_percent() -> None:
    drone = FakeDrone(
        FakeTelemetry(
            {
                "flight_mode": [FakeFlightMode.HOLD],
                "armed": [True],
                "in_air": [False],
                "position": [FakePosition(0.4)],
                "battery": [FakeBattery(87.0)],
            }
        )
    )
    tracker, errors = run_pumps(drone, Clock(3.0))
    snap = tracker.snapshot(3.0)
    assert snap.flight_mode == "HOLD" and snap.armed and not snap.in_air
    assert snap.relative_altitude_m == pytest.approx(0.4)
    assert snap.battery_remaining_fraction == pytest.approx(0.87)
    assert snap.telemetry_age_s == 0.0
    # Finite fake generators end; each end is recorded, not swallowed.
    assert set(errors) == set(Stream)
    assert all(v == "stream ended" for v in errors.values())


def test_failed_stream_recorded_and_snapshot_goes_stale() -> None:
    clock = Clock(1.0)
    drone = FakeDrone(
        FakeTelemetry(
            {
                "flight_mode": ["HOLD"],
                "armed": [True],
                "in_air": [False],
                "position": [FakePosition(0.0)],
                "battery": [FakeBattery(90.0)],
            },
            fail={"battery"},
        )
    )
    tracker, errors = run_pumps(drone, clock)
    assert errors[Stream.BATTERY] == "RuntimeError: battery broke"
    assert tracker.snapshot(1.0 + 1.5).telemetry_age_s == pytest.approx(1.5)


def test_malformed_values_become_unknown_not_crashes() -> None:
    drone = FakeDrone(
        FakeTelemetry(
            {
                "flight_mode": ["HOLD"],
                "armed": [True],
                "in_air": [False],
                "position": [object()],  # no relative_altitude_m
                "battery": [FakeBattery(250.0)],  # out of range
            }
        )
    )
    tracker, errors = run_pumps(drone, Clock(0.0))
    assert Stream.POSITION in tracker.missing_streams()
    assert math.isinf(tracker.snapshot(0.0).telemetry_age_s)
    assert all(v == "stream ended" for v in errors.values())


# ------------------------------------------------------- MAVSDK alert adapter
class FakeStatusTextType(Enum):
    INFO = 1
    NOTICE = 2
    WARNING = 3
    CRITICAL = 5


class FakeServerUtility:
    def __init__(self) -> None:
        self.calls = []

    async def send_status_text(self, type, text):  # noqa: A002 - MAVSDK signature
        self.calls.append((type, text))


def test_status_text_sender_maps_severity_by_name() -> None:
    drone = type("D", (), {})()
    drone.server_utility = FakeServerUtility()
    send = mavsdk_status_text_sender(drone, FakeStatusTextType)
    ok = asyncio.run(send(StatusMessage(AlertSeverity.CRITICAL, "COYOTE AUTONOMY OFF: X")))
    assert ok is True
    assert drone.server_utility.calls == [(FakeStatusTextType.CRITICAL, "COYOTE AUTONOMY OFF: X")]
