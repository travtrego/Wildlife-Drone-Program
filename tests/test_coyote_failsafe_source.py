"""Unit tests for the candidate HEARTBEAT ``system_status`` failsafe source.

Fake MAVSDK messages and clocks only. Nothing here shows what PX4 actually
reports in SITL or on the aircraft.
"""

import asyncio
import json
from dataclasses import dataclass

import pytest

from coyote.autonomy.delegation import DelegationAuthority, GrantCommand, RevocationReason
from coyote.autonomy.failsafe_source import (
    HEARTBEAT_SOURCE_KEY,
    HEARTBEAT_TRACKER_CONFIG,
    HeartbeatSourceConfig,
    failsafe_from_heartbeat,
    failsafe_from_system_status,
    pump_failsafe_heartbeat,
)
from coyote.autonomy.telemetry import TelemetryTracker, observe_vehicle


@dataclass
class FakeMessage:
    """Shape of MAVSDK 3.x ``mavlink_direct.MavlinkMessage``."""

    message_name: str
    system_id: int
    component_id: int
    fields_json: str
    target_system_id: int = 0
    target_component_id: int = 0


def heartbeat(status, *, sysid=1, compid=1, autopilot=12) -> FakeMessage:
    fields = {"type": 2, "autopilot": autopilot, "base_mode": 0, "custom_mode": 0}
    fields["system_status"] = status
    return FakeMessage("HEARTBEAT", sysid, compid, json.dumps(fields))


# ---------------------------------------------------------------- mapping
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (3, False),  # STANDBY
        (4, False),  # ACTIVE
        (5, True),  # CRITICAL
        (6, True),  # EMERGENCY
        (8, True),  # FLIGHT_TERMINATION
        (0, None),  # UNINIT
        (1, None),  # BOOT
        (2, None),  # CALIBRATING
        (7, None),  # POWEROFF
        (99, None),
        ("MAV_STATE_CRITICAL", True),
        ("mav_state_active", False),
        ("ACTIVE", None),  # not a full MAVLink name: unknown, not guessed
        (True, None),  # bool is not an enum value
        (None, None),
        (4.0, None),
    ],
)
def test_system_status_mapping_is_conservative(status, expected) -> None:
    assert failsafe_from_system_status(status) is expected


def test_only_autopilot_heartbeats_are_relevant() -> None:
    # A ground station or the Jetson's own heartbeat must not clear a failsafe.
    assert failsafe_from_heartbeat(heartbeat(4, sysid=255, compid=190)) == (False, None)
    assert failsafe_from_heartbeat(heartbeat(4, compid=191)) == (False, None)  # companion
    assert failsafe_from_heartbeat(heartbeat(4, compid=154)) == (False, None)  # gimbal
    other = FakeMessage("SYS_STATUS", 1, 1, "{}")
    assert failsafe_from_heartbeat(other) == (False, None)
    assert failsafe_from_heartbeat(heartbeat(5)) == (True, True)


def test_configured_autopilot_identity_is_used() -> None:
    cfg = HeartbeatSourceConfig(autopilot_system_id=7)
    assert failsafe_from_heartbeat(heartbeat(4, sysid=7), cfg) == (True, False)
    assert failsafe_from_heartbeat(heartbeat(4, sysid=1), cfg) == (False, None)


@pytest.mark.parametrize(
    "message",
    [
        FakeMessage("HEARTBEAT", 1, 1, "{not json"),
        FakeMessage("HEARTBEAT", 1, 1, "[4]"),
        FakeMessage("HEARTBEAT", 1, 1, json.dumps({"autopilot": 12})),  # no system_status
        heartbeat(4, autopilot=3),  # ArduPilot: PX4 meaning of system_status not assumed
        heartbeat(4, autopilot=8),  # MAV_AUTOPILOT_INVALID
    ],
)
def test_malformed_or_non_px4_autopilot_heartbeat_is_unknown(message) -> None:
    assert failsafe_from_heartbeat(message) == (True, None)


@pytest.mark.parametrize(
    "kwargs",
    [{"autopilot_system_id": 0}, {"autopilot_component_id": 256}, {"autopilot_system_id": True}],
)
def test_invalid_identity_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        HeartbeatSourceConfig(**kwargs).validate()


# ------------------------------------------------------------------- pump
class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeMavlinkDirect:
    def __init__(self, messages, clock: Clock, *, step_s=1.0, error=None) -> None:
        self.messages, self.clock, self.step_s, self.error = messages, clock, step_s, error
        self.requested: list[str] = []

    async def message(self, name: str):
        self.requested.append(name)
        for message in self.messages:
            yield message
            self.clock.t += self.step_s
        if self.error is not None:
            raise self.error


@dataclass
class FakeDrone:
    mavlink_direct: FakeMavlinkDirect


def run_pump(drone, tracker, clock, errors) -> None:
    asyncio.run(pump_failsafe_heartbeat(drone, tracker, clock, errors))


def test_pump_feeds_tracker_and_ignores_other_components() -> None:
    clock = Clock(10.0)
    tracker = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG)
    # Autopilot CRITICAL, then a GCS heartbeat claiming STANDBY: must stay True.
    drone = FakeDrone(
        FakeMavlinkDirect([heartbeat(5), heartbeat(3, sysid=255, compid=190)], clock, step_s=0.4)
    )
    errors: dict = {}
    run_pump(drone, tracker, clock, errors)
    assert drone.mavlink_direct.requested == ["HEARTBEAT"]
    assert tracker.failsafe_active(clock.t) is True
    assert errors == {HEARTBEAT_SOURCE_KEY: "stream ended"}


def test_pump_records_stream_failure() -> None:
    clock = Clock(0.0)
    tracker = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG)
    drone = FakeDrone(FakeMavlinkDirect([heartbeat(4)], clock, error=ConnectionError("gone")))
    errors: dict = {}
    run_pump(drone, tracker, clock, errors)
    assert errors[HEARTBEAT_SOURCE_KEY] == "ConnectionError: gone"


# ------------------------------------------------- with the R6 authority
def feed_streams(tracker: TelemetryTracker, t: float, *, armed=True, in_air=False) -> None:
    tracker.update_flight_mode("HOLD", t)
    tracker.update_armed(armed, t)
    tracker.update_in_air(in_air, t)
    tracker.update_position(0.0, t)
    tracker.update_battery_percent(95.0, t)


def test_healthy_heartbeat_allows_grant_and_critical_revokes() -> None:
    tracker, authority = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG), DelegationAuthority()
    feed_streams(tracker, 0.0)
    _, fs = failsafe_from_heartbeat(heartbeat(4))
    tracker.update_failsafe(fs, 0.0)
    observe_vehicle(tracker, authority, 0.0)
    assert authority.request_grant(GrantCommand(1, 0.0), 0.0).accepted

    feed_streams(tracker, 0.5)
    _, fs = failsafe_from_heartbeat(heartbeat(5))
    tracker.update_failsafe(fs, 0.5)
    observe_vehicle(tracker, authority, 0.5)
    assert not authority.delegated(0.5)
    assert [a.reason for a in authority.drain_alerts()] == [RevocationReason.PX4_FAILSAFE]


def test_boot_or_calibrating_heartbeat_refuses_grant() -> None:
    tracker, authority = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG), DelegationAuthority()
    feed_streams(tracker, 0.0, armed=False)
    tracker.update_failsafe(failsafe_from_heartbeat(heartbeat(2))[1], 0.0)
    observe_vehicle(tracker, authority, 0.0)
    assert not authority.request_grant(GrantCommand(1, 0.0), 0.0).accepted


def test_heartbeat_config_tolerates_1hz_but_revokes_when_heartbeats_stop() -> None:
    tracker, authority = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG), DelegationAuthority()
    feed_streams(tracker, 0.0)
    tracker.update_failsafe(False, 0.0)
    observe_vehicle(tracker, authority, 0.0)
    assert authority.request_grant(GrantCommand(1, 0.0), 0.0).accepted

    t = 0.0
    for _ in range(10):  # 1 Hz heartbeat, telemetry streams at 5 Hz
        for _ in range(5):
            t = round(t + 0.2, 6)
            feed_streams(tracker, t)
            observe_vehicle(tracker, authority, t)
        tracker.update_failsafe(False, t)
    assert authority.delegated(t)

    for _ in range(13):  # heartbeats stop, other streams continue for 2.6 s
        t = round(t + 0.2, 6)
        feed_streams(tracker, t)
        observe_vehicle(tracker, authority, t)
    assert not authority.delegated(t)
    assert [a.reason for a in authority.drain_alerts()] == [RevocationReason.FAILSAFE_STATE_UNKNOWN]


def test_default_1s_failsafe_age_is_too_tight_for_a_1hz_heartbeat() -> None:
    """Why HEARTBEAT_TRACKER_CONFIG exists: a slightly late heartbeat revokes."""

    tracker, authority = TelemetryTracker(), DelegationAuthority()
    feed_streams(tracker, 0.0)
    tracker.update_failsafe(False, 0.0)
    observe_vehicle(tracker, authority, 0.0)
    assert authority.request_grant(GrantCommand(1, 0.0), 0.0).accepted
    feed_streams(tracker, 1.05)  # next heartbeat 50 ms late
    observe_vehicle(tracker, authority, 1.05)
    assert not authority.delegated(1.05)
