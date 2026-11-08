"""Unit tests for the candidate COMMAND_ACK reply to the R6 grant/revoke command.

Fake MAVSDK messages, streams, senders and clocks only. Nothing here shows that
MAVSDK sends the reply with the companion's ids, that PX4 forwards it to the
ground link, or that MAVSDK does not also answer the command itself.
"""

import asyncio
import json
from dataclasses import dataclass

import pytest

from coyote.autonomy.action_gate import VehicleSnapshot
from coyote.autonomy.delegation import DelegationAuthority, GrantResult, RevocationReason
from coyote.autonomy.grant_transport import (
    ACTION_GRANT,
    ACTION_REVOKE,
    MAV_CMD_USER_1,
    MAV_RESULT_ACCEPTED,
    MAV_RESULT_DENIED,
    GrantTransportConfig,
    GroundCommand,
    GroundCommandKind,
    command_ack_fields,
    decode_ground_command,
    mavsdk_ack_sender,
    pump_ground_commands,
)
from coyote.ground.grant_sender import (
    AckOutcome,
    grant_command_fields,
    interpret_grant_ack,
    revoke_command_fields,
)

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


def ground_message(fields, sysid=255, compid=190) -> FakeMessage:
    return FakeMessage("COMMAND_LONG", sysid, compid, json.dumps(fields))


def ack_message(fields, sysid=1, compid=191) -> FakeMessage:
    return FakeMessage("COMMAND_ACK", sysid, compid, json.dumps(fields))


def eligible_authority(now: float = 10.0) -> DelegationAuthority:
    auth = DelegationAuthority()
    auth.observe(ON_GROUND_ARMED, False, now)
    return auth


class FakeMavlinkDirect:
    def __init__(self, messages, error: Exception | None = None) -> None:
        self._messages = messages
        self._error = error

    async def message(self, name):
        for msg in self._messages:
            yield msg
        if self._error is not None:
            raise self._error


class FakeDrone:
    def __init__(self, messages) -> None:
        self.mavlink_direct = FakeMavlinkDirect(messages)


def run_pump(auth, messages, send_ack, times, **kwargs):
    log = {"commands": [], "acks": [], "errors": {}}
    clock = iter(times)
    asyncio.run(
        pump_ground_commands(
            FakeDrone(messages), auth, lambda: next(clock), log["errors"],
            on_command=lambda t, cmd, res: log["commands"].append((cmd.kind, res.accepted)),
            send_ack=send_ack,
            on_ack=lambda t, fields, err: log["acks"].append((fields, err)),
            **kwargs,
        )
    )
    return log


class RecordingSender:
    def __init__(self, fail_with: Exception | None = None, delay_s: float = 0.0) -> None:
        self.sent: list[dict] = []
        self.fail_with = fail_with
        self.delay_s = delay_s

    async def __call__(self, fields) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(fields)


# ----------------------------------------------------------- reply mapping


def test_ack_mapping_accepted_refused_revoke_and_rejected() -> None:
    accepted = command_ack_fields(
        GroundCommand(GroundCommandKind.GRANT, 7), GrantResult(True, "delegation granted")
    )
    assert accepted == {
        "command": MAV_CMD_USER_1,
        "result": MAV_RESULT_ACCEPTED,
        "progress": 0,
        "result_param2": 7,
        "target_system": 255,
        "target_component": 190,
    }
    refused = command_ack_fields(
        GroundCommand(GroundCommandKind.GRANT, 8), GrantResult(False, "stale")
    )
    assert refused["result"] == MAV_RESULT_DENIED and refused["result_param2"] == 8
    revoke = command_ack_fields(
        GroundCommand(GroundCommandKind.REVOKE), GrantResult(False, "revoked")
    )
    assert revoke["result"] == MAV_RESULT_ACCEPTED and revoke["result_param2"] == 0
    bad_action = command_ack_fields(
        GroundCommand(GroundCommandKind.REJECTED, None, "unknown action 3.0"),
        GrantResult(False, "rejected"),
    )
    assert bad_action["result"] == MAV_RESULT_DENIED and bad_action["result_param2"] == 0


def test_no_reply_to_unexpected_source_or_other_target() -> None:
    cfg = GrantTransportConfig()
    wrong_source = decode_ground_command(ground_message(grant_command_fields(3), sysid=254))
    fields = grant_command_fields(3)
    fields["target_component"] = 1  # addressed to the autopilot, not us
    wrong_target = decode_ground_command(ground_message(fields))
    fields["target_system"] = 0
    fields["target_component"] = 0
    broadcast = decode_ground_command(ground_message(fields))
    for cmd in (wrong_source, wrong_target, broadcast):
        assert cmd.kind is GroundCommandKind.REJECTED and cmd.ackable is False
        assert command_ack_fields(cmd, GrantResult(False, "x"), cfg) is None
    # A bad action from the right sender to us is answered (DENIED).
    bad = grant_command_fields(3)
    bad["param1"] = 9.0
    cmd = decode_ground_command(ground_message(bad))
    assert cmd.kind is GroundCommandKind.REJECTED and cmd.ackable is True


def test_reply_uses_configured_ids() -> None:
    cfg = GrantTransportConfig(ground_station_system_id=200, ground_station_component_id=1,
                               command_id=31011)
    fields = command_ack_fields(
        GroundCommand(GroundCommandKind.GRANT, 2), GrantResult(True, "ok"), cfg
    )
    assert (fields["target_system"], fields["target_component"], fields["command"]) == (
        200, 1, 31011,
    )


# --------------------------------------------------------------- the pump


def test_pump_replies_after_state_change_in_order() -> None:
    auth = eligible_authority()
    sender = RecordingSender()
    states_at_send: list[bool] = []

    async def send(fields):
        states_at_send.append(auth.delegated(10.25))
        await sender(fields)

    messages = [
        ground_message(grant_command_fields(4)),
        ground_message(grant_command_fields(4)),  # retransmission: refused, state unchanged
        ground_message(revoke_command_fields()),
        ground_message(grant_command_fields(5), sysid=254),  # unknown sender: no reply
    ]
    log = run_pump(auth, messages, send, [10.1, 10.11, 10.2, 10.21, 10.3, 10.31, 10.4, 10.5])
    results = [(f["result"], f["result_param2"]) for f in sender.sent]
    assert results == [
        (MAV_RESULT_ACCEPTED, 4),
        (MAV_RESULT_DENIED, 4),
        (MAV_RESULT_ACCEPTED, 0),
    ]
    # The authority had already acted when each reply went out.
    assert states_at_send == [True, True, False]
    assert [err for _, err in log["acks"]] == [None, None, None]
    assert len(log["commands"]) == 4


def test_failed_reply_never_changes_delegation_and_is_not_retried() -> None:
    auth = eligible_authority()
    sender = RecordingSender(fail_with=RuntimeError("link down"))
    log = run_pump(auth, [ground_message(grant_command_fields(4))], sender, [10.1, 10.2, 10.3])
    assert sender.sent == []
    assert len(log["acks"]) == 1 and "RuntimeError: link down" in log["acks"][0][1]
    # Grant stood until the command stream ended; that end revokes as before.
    alerts = auth.drain_alerts()
    assert [a.reason for a in alerts] == [RevocationReason.COMMAND_LINK_LOST]


def test_slow_reply_is_bounded_and_next_command_still_handled() -> None:
    auth = eligible_authority()
    sender = RecordingSender(delay_s=0.5)
    messages = [ground_message(grant_command_fields(4)), ground_message(revoke_command_fields())]
    log = run_pump(
        auth, messages, sender, [10.1, 10.2, 10.3, 10.4, 10.5], ack_timeout_s=0.01
    )
    assert [err for _, err in log["acks"]] == [
        "ack send timed out after 0.01 s",
        "ack send timed out after 0.01 s",
    ]
    assert log["commands"] == [(GroundCommandKind.GRANT, True), (GroundCommandKind.REVOKE, False)]
    assert [a.reason for a in auth.drain_alerts()][0] is RevocationReason.OPERATOR_REVOKED


def test_without_sender_pump_stays_read_only() -> None:
    auth = eligible_authority()
    log = run_pump(auth, [ground_message(grant_command_fields(4))], None, [10.1, 10.2])
    assert log["acks"] == []
    assert log["commands"] == [(GroundCommandKind.GRANT, True)]


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_ack_timeout_refused(bad) -> None:
    with pytest.raises(ValueError):
        run_pump(eligible_authority(), [], RecordingSender(), [10.1], ack_timeout_s=bad)


def test_mavsdk_sender_builds_companion_sourced_message() -> None:
    pytest.importorskip("mavsdk")
    sent = []

    class Direct:
        async def send_message(self, message):
            sent.append(message)

    class Drone:
        mavlink_direct = Direct()

    fields = command_ack_fields(
        GroundCommand(GroundCommandKind.GRANT, 9), GrantResult(True, "ok")
    )
    asyncio.run(mavsdk_ack_sender(Drone())(fields))
    (msg,) = sent
    assert msg.message_name == "COMMAND_ACK"
    assert (msg.system_id, msg.component_id) == (1, 191)
    assert (msg.target_system_id, msg.target_component_id) == (255, 190)
    assert json.loads(msg.fields_json) == fields


# --------------------------------------------------------- ground decoding


def companion_reply(command_kind, sequence, accepted) -> FakeMessage:
    fields = command_ack_fields(
        GroundCommand(command_kind, sequence), GrantResult(accepted, "")
    )
    return ack_message(fields)


def test_ground_round_trip_confirmed_refused_and_revoke() -> None:
    ok = interpret_grant_ack(companion_reply(GroundCommandKind.GRANT, 6, True), 6)
    assert ok.outcome is AckOutcome.CONFIRMED
    no = interpret_grant_ack(companion_reply(GroundCommandKind.GRANT, 6, False), 6)
    assert no.outcome is AckOutcome.REFUSED and no.result == MAV_RESULT_DENIED
    revoke = interpret_grant_ack(companion_reply(GroundCommandKind.REVOKE, None, False), 0)
    assert revoke.outcome is AckOutcome.CONFIRMED


def test_ground_never_confirms_a_reply_that_does_not_match() -> None:
    good = command_ack_fields(GroundCommand(GroundCommandKind.GRANT, 6), GrantResult(True, ""))
    # Reply for an older grant.
    assert interpret_grant_ack(ack_message(good), 7).outcome is AckOutcome.UNMATCHED
    # Reply claiming to be accepted but from the autopilot (e.g. PX4 or MAVSDK itself).
    assert interpret_grant_ack(ack_message(good, compid=1), 6).outcome is AckOutcome.UNMATCHED
    # Addressed to another ground station.
    other = dict(good, target_system=254)
    assert interpret_grant_ack(ack_message(other), 6).outcome is AckOutcome.UNMATCHED
    # A reply without the sequence echo (for example an automatic answer).
    bare = dict(good, result_param2=0)
    assert interpret_grant_ack(ack_message(bare), 6).outcome is AckOutcome.UNMATCHED
    # Garbled result value.
    garbled = dict(good, result="yes")
    assert interpret_grant_ack(ack_message(garbled), 6).outcome is AckOutcome.UNMATCHED


def test_ground_ignores_other_messages_and_commands() -> None:
    good = command_ack_fields(GroundCommand(GroundCommandKind.GRANT, 6), GrantResult(True, ""))
    assert interpret_grant_ack(FakeMessage("HEARTBEAT", 1, 191, "{}"), 6) is None
    assert interpret_grant_ack(ack_message(dict(good, command=400)), 6) is None
    assert interpret_grant_ack(FakeMessage("COMMAND_ACK", 1, 191, "not json"), 6) is None


@pytest.mark.parametrize("bad", [-1, 2**24 + 1, True, 1.0])
def test_ground_rejects_bad_expected_sequence(bad) -> None:
    msg = companion_reply(GroundCommandKind.GRANT, 6, True)
    with pytest.raises(ValueError):
        interpret_grant_ack(msg, bad)


def test_action_codes_unchanged() -> None:
    # The reply mapping relies on these; guard against silent renumbering.
    assert (ACTION_GRANT, ACTION_REVOKE) == (1, 2)
