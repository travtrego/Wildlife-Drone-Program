"""Unit tests for the Coyote watch-only SITL script's guard and observation helpers.

Fakes only. Nothing here shows PX4 SITL behaviour.
"""

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from coyote.autonomy.delegation import DelegationAuthority, RevocationReason
from coyote.autonomy.failsafe_source import (
    HEARTBEAT_TRACKER_CONFIG,
    HeartbeatSourceConfig,
    subscribe_failsafe_heartbeat,
)
from coyote.autonomy.ground_alerts import AlertSeverity, StatusMessage
from coyote.autonomy.telemetry import TelemetryTracker, observe_vehicle
from coyote.autonomy.vehicle_link import WatchTick, subscribe_vehicle_telemetry
from shared.autonomy.sitl import SitlMissionConfig
from simulation.mavsdk.coyote_delegation_watch import (
    ObservationLog,
    handle_keys,
    observing_drone,
    run_watch,
    status_line,
    tick_reporter,
)


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@dataclass
class Msg:
    message_name: str
    system_id: int
    component_id: int
    fields_json: str


def hb(status, sysid=1, compid=1) -> Msg:
    return Msg("HEARTBEAT", sysid, compid, json.dumps({"autopilot": 12, "system_status": status}))


def gen(*values, clock: Clock | None = None, step: float = 0.1):
    async def source(*_args):
        for value in values:
            yield value
            if clock is not None:
                clock.t += step

    return source


def fake_drone(clock: Clock, heartbeats=()):
    telemetry = SimpleNamespace(
        flight_mode=gen(SimpleNamespace(name="HOLD")),
        armed=gen(False),
        in_air=gen(False),
        position=gen(SimpleNamespace(relative_altitude_m=0.0)),
        battery=gen(SimpleNamespace(remaining_percent=90.0)),
    )
    return SimpleNamespace(
        telemetry=telemetry,
        mavlink_direct=SimpleNamespace(message=gen(*heartbeats, clock=clock, step=1.0)),
        action=SimpleNamespace(arm="must not be reachable"),
    )


# ------------------------------------------------------------ endpoint guard
@pytest.mark.parametrize(
    "address",
    ["udpin://0.0.0.0:14540", "udpin://192.168.1.20:14540", "serial:///dev/ttyACM0:57600"],
)
def test_watch_refuses_non_sitl_endpoints_before_connecting(address) -> None:
    with pytest.raises(ValueError, match="simulation-only"):
        asyncio.run(
            run_watch(
                SitlMissionConfig(system_address=address), 10.0, False, HeartbeatSourceConfig()
            )
        )


def test_watch_rejects_bad_duration() -> None:
    with pytest.raises(ValueError, match="duration"):
        asyncio.run(run_watch(SitlMissionConfig(), 0.0, False, HeartbeatSourceConfig()))


# --------------------------------------------------------- read-only facade
def test_facade_exposes_no_command_plugins() -> None:
    clock = Clock()
    facade = observing_drone(fake_drone(clock), ObservationLog(0.0), clock, HeartbeatSourceConfig())
    for plugin in ("action", "mission", "offboard", "server_utility", "param"):
        assert not hasattr(facade, plugin)


def test_facade_counts_streams_and_feeds_the_real_pumps() -> None:
    clock = Clock(5.0)
    log = ObservationLog(started_s=5.0)
    heartbeats = (hb(3), hb(3, sysid=255, compid=190), hb(5), hb(3))
    facade = observing_drone(fake_drone(clock, heartbeats), log, clock, HeartbeatSourceConfig())
    tracker = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG)
    errors: dict = {}

    async def run() -> None:
        tasks = subscribe_vehicle_telemetry(facade, tracker, clock, errors)
        tasks.append(subscribe_failsafe_heartbeat(facade, tracker, clock, errors))
        await asyncio.gather(*tasks)

    asyncio.run(run())
    assert log.message_counts["flight_mode"] == 1
    assert log.message_counts["autopilot_heartbeat"] == 3  # GCS heartbeat not counted
    assert log.heartbeat_sources[(255, 190)] == 1
    assert dict(log.system_status_values) == {"3": 2, "5": 1}
    assert log.rate_hz("autopilot_heartbeat") == pytest.approx(2 / 3)
    assert tracker.failsafe_active(clock.t) is False  # last autopilot heartbeat STANDBY
    summary = "\n".join(log.summary_lines())
    assert "(255, 190): 1" in summary and '"system_status": 5' in summary


def test_rate_is_unknown_with_fewer_than_two_messages() -> None:
    log = ObservationLog(0.0)
    log.message("armed", 1.0)
    assert log.rate_hz("armed") is None and log.rate_hz("battery") is None


# ------------------------------------------------------------- keys / ticks
def healthy(tracker: TelemetryTracker, t: float) -> None:
    tracker.update_flight_mode("HOLD", t)
    tracker.update_armed(True, t)
    tracker.update_in_air(False, t)
    tracker.update_position(0.0, t)
    tracker.update_battery_percent(90.0, t)
    tracker.update_failsafe(False, t)


def run_keys(keys, authority, clock, log=None):
    async def run():
        lines: asyncio.Queue = asyncio.Queue()
        for key in keys:
            lines.put_nowait(key)
        stop = asyncio.Event()
        await handle_keys(lines, authority, log or ObservationLog(0.0), clock, stop)
        return stop.is_set()

    return asyncio.run(run())


def test_grant_key_is_refused_without_a_healthy_observation() -> None:
    clock, authority = Clock(1.0), DelegationAuthority()
    log = ObservationLog(0.0)
    run_keys(["g\n", None], authority, clock, log)
    assert not authority.delegated(1.0)
    assert "accepted=False" in log.events[0][1]


def test_grant_then_revoke_keys_and_quit() -> None:
    clock, authority, tracker = Clock(1.0), DelegationAuthority(), TelemetryTracker()
    healthy(tracker, 1.0)
    observe_vehicle(tracker, authority, 1.0)
    assert run_keys(["g\n", "r\n", "q\n"], authority, clock) is True
    assert not authority.delegated(1.0)
    assert [a.reason for a in authority.drain_alerts()] == [RevocationReason.OPERATOR_REVOKED]


def test_tick_reporter_logs_transitions_and_alerts_once() -> None:
    clock, log = Clock(2.0), ObservationLog(0.0)
    report = tick_reporter(log, clock)
    msg = StatusMessage(AlertSeverity.WARNING, "COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST")
    report(WatchTick(True, None, False, 0))
    report(WatchTick(True, None, False, 0))
    report(WatchTick(False, msg, False, 0))
    texts = [text for _, text in log.events]
    assert texts == [
        "delegated -> True",
        "delegated -> False",
        "alert sent (WARNING): COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST",
    ]


def test_status_line_shows_unknown_state_honestly() -> None:
    line = status_line(TelemetryTracker(), DelegationAuthority(), 0.0)
    assert "mode=UNKNOWN" in line and "age=inf" in line and "failsafe=None" in line
