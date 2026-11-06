"""Unit tests for the candidate R6 grant/revoke COMMAND_LONG transport.

Fake MAVSDK messages, streams and clocks only. Nothing here shows that PX4
forwards the command to the companion, that MAVSDK delivers it, or that any
ground tool can send it.
"""

import asyncio
import json
from dataclasses import dataclass

import pytest

from coyote.autonomy.action_gate import VehicleSnapshot
from coyote.autonomy.delegation import DelegationAuthority, RevocationReason
from coyote.autonomy.grant_transport import (
    ACTION_GRANT,
    ACTION_REVOKE,
    COMMAND_SOURCE_KEY,
    MAV_CMD_USER_1,
    GrantTransportConfig,
    GroundCommand,
    GroundCommandKind,
    apply_ground_command,
    decode_ground_command,
    pump_ground_commands,
)
from coyote.autonomy.ground_alerts import format_status_text

ON_GROUND_ARMED = VehicleSnapshot(
    flight_mode="HOLD",
    armed=True,
    in_air=False,
    relative_altitude_m=0.0,
    battery_remaining_fraction=1.0,
    telemetry_age_s=0.1,
)


@dataclass
class FakeMessage:
    """Shape of MAVSDK 3.x ``mavlink_direct.MavlinkMessage``."""

    message_name: str
    system_id: int
    component_id: int
    fields_json: str
    target_system_id: int = 0
    target_component_id: int = 0


def _as_param(value):
    """MAVLink params are floats; keep bools/None/odd values as-is to test them."""

    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def command_long(
    action=ACTION_GRANT,
    seq=1,
    *,
    sysid=255,
    compid=190,
    target_system=1,
    target_component=191,
    command=MAV_CMD_USER_1,
    confirmation=0,
) -> FakeMessage:
    fields = {
        "target_system": target_system,
        "target_component": target_component,
        "command": command,
        "confirmation": confirmation,
        "param1": _as_param(action),
        "param2": _as_param(seq),
        "param3": 0.0,
        "param4": 0.0,
        "param5": 0.0,
        "param6": 0.0,
        "param7": 0.0,
    }
    return FakeMessage("COMMAND_LONG", sysid, compid, json.dumps(fields))


def eligible_authority(t: float = 10.0) -> DelegationAuthority:
    auth = DelegationAuthority()
    auth.observe(ON_GROUND_ARMED, failsafe_active=False, now_s=t)
    return auth


# ------------------------------------------------------------------ decoding
def test_grant_and_revoke_decode() -> None:
    grant = decode_ground_command(command_long(ACTION_GRANT, 7))
    assert grant == GroundCommand(GroundCommandKind.GRANT, 7, "operator grant")
    revoke = decode_ground_command(command_long(ACTION_REVOKE, 0))
    assert revoke is not None and revoke.kind is GroundCommandKind.REVOKE


def test_unrelated_messages_are_ignored() -> None:
    assert decode_ground_command(FakeMessage("HEARTBEAT", 255, 190, "{}")) is None
    assert decode_ground_command(command_long(command=400)) is None  # ARM_DISARM: not ours
    assert decode_ground_command(FakeMessage("COMMAND_LONG", 255, 190, "not json")) is None
    assert decode_ground_command(FakeMessage("COMMAND_LONG", 255, 190, "[1, 2]")) is None


@pytest.mark.parametrize(
    "message",
    [
        command_long(sysid=1, compid=1),  # the autopilot itself
        command_long(compid=191),  # another companion process
        command_long(sysid=254),  # a second ground station
        command_long(target_component=1),  # addressed to the autopilot
        command_long(target_component=0),  # broadcast
        command_long(target_system=0),
        command_long(target_system=2),
    ],
)
def test_wrong_source_or_target_is_rejected(message) -> None:
    decoded = decode_ground_command(message)
    assert decoded is not None and decoded.kind is GroundCommandKind.REJECTED


@pytest.mark.parametrize(
    ("action", "seq"),
    [
        (0, 1),  # all-zero / default action does nothing
        (3, 1),
        (1.5, 1),
        (ACTION_GRANT, 0),
        (ACTION_GRANT, -1),
        (ACTION_GRANT, 2.5),
        (ACTION_GRANT, 2**24 + 1),
        (ACTION_GRANT, float("nan")),
        (ACTION_GRANT, None),
        (True, 1),
    ],
)
def test_bad_action_or_sequence_is_rejected(action, seq) -> None:
    decoded = decode_ground_command(command_long(action, seq))
    assert decoded is not None and decoded.kind is GroundCommandKind.REJECTED


def test_configured_identities_are_used() -> None:
    cfg = GrantTransportConfig(ground_station_system_id=200, companion_component_id=195)
    msg = command_long(sysid=200, target_component=195)
    assert decode_ground_command(msg, cfg).kind is GroundCommandKind.GRANT
    assert decode_ground_command(command_long(), cfg).kind is GroundCommandKind.REJECTED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ground_station_system_id": 0},
        {"companion_component_id": 256},
        {"companion_system_id": True},
        {"command_id": -1},
        {"command_id": 70000},
    ],
)
def test_invalid_config_is_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        GrantTransportConfig(**kwargs).validate()


# ------------------------------------------------------------ authority use
def test_decoded_grant_goes_through_authority_rules() -> None:
    auth = eligible_authority()
    result = apply_ground_command(decode_ground_command(command_long(seq=1)), auth, 10.1)
    assert result.accepted and auth.delegated(10.1)
    # A retransmission reuses the sequence: refused, but state is unchanged.
    again = apply_ground_command(decode_ground_command(command_long(seq=1)), auth, 10.2)
    assert not again.accepted and auth.delegated(10.2)


def test_grant_refused_while_failsafe_active() -> None:
    auth = DelegationAuthority()
    auth.observe(ON_GROUND_ARMED, failsafe_active=True, now_s=10.0)
    result = apply_ground_command(decode_ground_command(command_long()), auth, 10.1)
    assert not result.accepted and not auth.delegated(10.1)


def test_rejected_command_never_changes_state() -> None:
    auth = eligible_authority()
    rejected = decode_ground_command(command_long(sysid=1, compid=1))
    assert not apply_ground_command(rejected, auth, 10.1).accepted
    assert not auth.delegated(10.1)
    # A rejected command must not burn the sequence either.
    assert apply_ground_command(decode_ground_command(command_long(seq=1)), auth, 10.2).accepted


def test_revoke_command_revokes_with_alert() -> None:
    auth = eligible_authority()
    apply_ground_command(decode_ground_command(command_long(seq=1)), auth, 10.1)
    apply_ground_command(decode_ground_command(command_long(ACTION_REVOKE)), auth, 10.2)
    assert not auth.delegated(10.2)
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.OPERATOR_REVOKED


# ----------------------------------------------------------------- the pump
class FakeMavlinkDirect:
    def __init__(self, messages, error: Exception | None = None) -> None:
        self._messages = messages
        self._error = error
        self.subscribed: list[str] = []

    async def message(self, name):
        self.subscribed.append(name)
        for msg in self._messages:
            yield msg
        if self._error is not None:
            raise self._error


class FakeDrone:
    def __init__(self, messages, error: Exception | None = None) -> None:
        self.mavlink_direct = FakeMavlinkDirect(messages, error)


def test_pump_applies_commands_and_logs_each() -> None:
    auth = eligible_authority()
    drone = FakeDrone(
        [
            FakeMessage("HEARTBEAT", 1, 1, "{}"),
            command_long(sysid=254),  # rejected, logged
            command_long(seq=3),  # accepted
        ]
    )
    times = iter([10.1, 10.2, 10.3])
    log: list[tuple[GroundCommandKind, bool]] = []
    errors: dict = {}
    asyncio.run(
        pump_ground_commands(
            drone, auth, lambda: next(times), errors,
            on_command=lambda t, cmd, res: log.append((cmd.kind, res.accepted)),
        )
    )
    assert drone.mavlink_direct.subscribed == ["COMMAND_LONG"]
    assert log == [(GroundCommandKind.REJECTED, False), (GroundCommandKind.GRANT, True)]
    # The fake stream then ends: the command channel is gone, so authority goes.
    assert errors[COMMAND_SOURCE_KEY] == "stream ended"
    assert not auth.delegated(10.3)
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.COMMAND_LINK_LOST
    assert format_status_text(alert).text == "COYOTE AUTONOMY OFF: GROUND CMD LINK LOST"


def test_pump_records_stream_error_and_revokes() -> None:
    auth = eligible_authority()
    drone = FakeDrone([command_long(seq=1)], error=RuntimeError("link reset"))
    times = iter([10.1, 10.2])
    errors: dict = {}
    asyncio.run(pump_ground_commands(drone, auth, lambda: next(times), errors))
    assert errors[COMMAND_SOURCE_KEY] == "RuntimeError: link reset"
    assert not auth.delegated(10.2)
    assert auth.drain_alerts()[0].reason is RevocationReason.COMMAND_LINK_LOST


def test_pump_without_grant_does_not_alert_on_stream_end() -> None:
    auth = eligible_authority()
    errors: dict = {}
    asyncio.run(pump_ground_commands(FakeDrone([]), auth, lambda: 10.1, errors))
    assert errors[COMMAND_SOURCE_KEY] == "stream ended"
    assert auth.drain_alerts() == ()  # alerts only on a delegated -> revoked transition


def test_pump_rejects_invalid_config_before_subscribing() -> None:
    drone = FakeDrone([])
    with pytest.raises(ValueError):
        asyncio.run(
            pump_ground_commands(
                drone, eligible_authority(), lambda: 0.0, {},
                GrantTransportConfig(command_id=-5),
            )
        )
    assert drone.mavlink_direct.subscribed == []
