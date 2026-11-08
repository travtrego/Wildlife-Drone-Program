"""Unit tests for the candidate second-link R6 command receive path and ground reply display.

Fake pymavlink connections and clocks only. The PX4 SIH SITL observation of
2026-11-08 is recorded separately; these tests do not reproduce PX4 forwarding.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from coyote.autonomy.action_gate import VehicleSnapshot
from coyote.autonomy.command_link import (
    MAV_TYPE_ONBOARD_CONTROLLER,
    CommandLink,
    CommandLinkConfig,
    DirectMessage,
    to_direct_message,
)
from coyote.autonomy.delegation import DelegationAuthority, GrantResult, RevocationReason
from coyote.autonomy.grant_transport import (
    MAV_CMD_USER_1,
    GrantTransportConfig,
    GroundCommand,
    GroundCommandKind,
    command_ack_fields,
    pump_ground_commands,
)
from coyote.ground.grant_sender import grant_command_fields, revoke_command_fields
from simulation.mavsdk.coyote_ground_sender import await_reply

CONFIG = GrantTransportConfig()
ON_GROUND = VehicleSnapshot("HOLD", False, False, 0.0, 1.0, 0.1)


class FakeRaw:
    """Shape of a pymavlink message."""

    def __init__(self, name, sysid, compid, fields) -> None:
        self._name, self._sys, self._comp, self._fields = name, sysid, compid, fields

    def get_type(self):
        return self._name

    def get_srcSystem(self):
        return self._sys

    def get_srcComponent(self):
        return self._comp

    def to_dict(self):
        return {"mavpackettype": self._name, **self._fields}


class FakeMav:
    def __init__(self, sysid=1, compid=191) -> None:
        self.srcSystem, self.srcComponent = sysid, compid
        self.heartbeats: list[tuple] = []
        self.acks: list[tuple] = []

    def heartbeat_send(self, *args):
        self.heartbeats.append(args)

    def command_ack_send(self, *args):
        self.acks.append(args)


class FakeConnection:
    def __init__(self, incoming, error: Exception | None = None, sysid=1, compid=191) -> None:
        self.mav = FakeMav(sysid, compid)
        self._incoming = list(incoming)
        self._error = error

    def recv_match(self, type=None, blocking=True, timeout=None):
        while self._incoming:
            msg = self._incoming.pop(0)
            if msg is None or msg.get_type() == type:
                return msg
        if self._error is not None:
            raise self._error
        raise OSError("fake link closed")


def command(fields, sysid=255, compid=190) -> FakeRaw:
    return FakeRaw("COMMAND_LONG", sysid, compid, fields)


def eligible_authority() -> DelegationAuthority:
    auth = DelegationAuthority()
    auth.observe(ON_GROUND, False, 10.0)
    return auth


def run_link(conn, times, auth=None):
    auth = auth or eligible_authority()
    link = CommandLink(conn, CONFIG, clock=lambda: 0.0)
    log = {"commands": [], "acks": [], "errors": {}}
    clock = iter(times)
    asyncio.run(
        pump_ground_commands(
            link, auth, lambda: next(clock), log["errors"], CONFIG,
            on_command=lambda t, c, r: log["commands"].append((c.kind, c.sequence, r.accepted)),
            send_ack=link.send_ack,
            on_ack=lambda t, f, e: log["acks"].append(e),
        )
    )
    return auth, conn, log


def test_to_direct_message_matches_decoder_shape() -> None:
    raw = command(grant_command_fields(3))
    msg = to_direct_message(raw)
    assert isinstance(msg, DirectMessage)
    assert (msg.message_name, msg.system_id, msg.component_id) == ("COMMAND_LONG", 255, 190)
    assert "mavpackettype" not in json.loads(msg.fields_json)
    assert json.loads(msg.fields_json)["param2"] == 3.0
    assert to_direct_message(FakeRaw("BAD_DATA", 0, 0, {})) is None


def test_grant_revoke_and_replies_through_link() -> None:
    conn = FakeConnection(
        [
            None,  # poll timeout: keep waiting
            command(grant_command_fields(4)),
            command(revoke_command_fields()),
            command(grant_command_fields(4)),  # replay: refused
            command(grant_command_fields(5), sysid=254),  # unknown sender: no reply
        ]
    )
    auth, conn, log = run_link(conn, [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8])
    assert log["commands"] == [
        (GroundCommandKind.GRANT, 4, True),
        (GroundCommandKind.REVOKE, None, False),
        (GroundCommandKind.GRANT, 4, False),
        (GroundCommandKind.REJECTED, None, False),
    ]
    # COMMAND_ACK args: command, result, progress, result_param2, target sys, target comp
    assert conn.mav.acks == [
        (MAV_CMD_USER_1, 0, 0, 4, 255, 190),
        (MAV_CMD_USER_1, 0, 0, 0, 255, 190),
        (MAV_CMD_USER_1, 2, 0, 4, 255, 190),
    ]
    # The link closing ends the stream: the operator can no longer revoke.
    assert [a.reason for a in auth.drain_alerts()] == [RevocationReason.OPERATOR_REVOKED]
    assert "OSError" in log["errors"]["ground_command"]


def test_link_error_while_delegated_revokes() -> None:
    conn = FakeConnection([command(grant_command_fields(7))], error=ConnectionResetError("gone"))
    auth, _, log = run_link(conn, [10.1, 10.2, 10.3])
    assert log["commands"] == [(GroundCommandKind.GRANT, 7, True)]
    assert [a.reason for a in auth.drain_alerts()] == [RevocationReason.COMMAND_LINK_LOST]


def test_heartbeat_sent_as_onboard_controller_at_interval() -> None:
    times = iter([0.0, 0.5, 1.0, 1.4, 2.1])
    conn = FakeConnection([None, None, None, None])
    link = CommandLink(conn, CONFIG, CommandLinkConfig(heartbeat_interval_s=1.0),
                       clock=lambda: next(times))

    async def drain():
        async for _ in link.messages("COMMAND_LONG"):
            pass

    with pytest.raises(OSError):
        asyncio.run(drain())
    assert len(conn.mav.heartbeats) == 3  # at 0.0, 1.0 and 2.1
    assert conn.mav.heartbeats[0][0] == MAV_TYPE_ONBOARD_CONTROLLER


def test_link_must_send_as_the_companion() -> None:
    with pytest.raises(ValueError):
        CommandLink(FakeConnection([], sysid=255, compid=190), CONFIG)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_bad_link_config_refused(bad) -> None:
    with pytest.raises(ValueError):
        CommandLink(FakeConnection([]), CONFIG, CommandLinkConfig(poll_timeout_s=bad))


# ---------------------------------------------------- ground reply display


def ack_msg(sequence, accepted, compid=191) -> SimpleNamespace:
    kind = GroundCommandKind.GRANT if sequence else GroundCommandKind.REVOKE
    fields = command_ack_fields(GroundCommand(kind, sequence or None), GrantResult(accepted, ""))
    return SimpleNamespace(message_name="COMMAND_ACK", system_id=1, component_id=compid,
                           fields_json=json.dumps(fields))


def reply_for(queued, expected, wait_s=0.05, late=()):
    async def run():
        acks: asyncio.Queue = asyncio.Queue()
        for m in queued:
            acks.put_nowait(m)
        task = asyncio.create_task(await_reply(acks, expected, CONFIG, wait_s))
        await asyncio.sleep(0)
        for m in late:
            acks.put_nowait(m)
        return await task

    return asyncio.run(run())


def test_reply_display_accepted_refused_and_none() -> None:
    assert reply_for([], 6, late=[ack_msg(6, True)]) == "companion ACCEPTED"
    assert reply_for([], 6, late=[ack_msg(6, False)]).startswith("companion REFUSED")
    assert reply_for([], 0, late=[ack_msg(0, True)]) == "companion ACCEPTED"
    assert reply_for([], 6).startswith("NO REPLY")


def test_reply_display_never_counts_stale_or_foreign_replies() -> None:
    # An accepted reply already queued from an earlier grant is discarded.
    assert reply_for([ack_msg(6, True)], 6).startswith("NO REPLY")
    # A reply from the autopilot component, or for another sequence, is ignored.
    late = [ack_msg(6, True, compid=1), ack_msg(5, True)]
    assert reply_for([], 6, late=late).startswith("NO REPLY")
