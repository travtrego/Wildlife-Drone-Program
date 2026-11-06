"""SITL-only ground sender and the watch's MAVLink grant path, with fakes only.

Nothing here shows PX4 SITL behaviour: whether PX4 forwards the command to
the companion link is exactly what a SITL session has to observe.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from coyote.autonomy.delegation import DelegationAuthority, GrantCommand, RevocationReason
from coyote.autonomy.failsafe_source import HeartbeatSourceConfig
from coyote.autonomy.grant_transport import (
    COMMAND_SOURCE_KEY,
    GrantTransportConfig,
    subscribe_ground_commands,
)
from coyote.autonomy.telemetry import TelemetryTracker, observe_vehicle
from coyote.ground.grant_sender import GrantSequenceError, GrantSequenceStore
from shared.autonomy.sitl import SitlMissionConfig
from simulation.mavsdk.coyote_delegation_watch import (
    ObservationLog,
    command_reporter,
    handle_keys,
    observing_drone,
    parse_args,
    run_watch,
)
from simulation.mavsdk.coyote_ground_sender import (
    command_message,
    handle_ground_keys,
    require_sitl_ground_address,
    run_sender,
    send_grant,
)

CONFIG = GrantTransportConfig()


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
    target_system_id: int
    target_component_id: int
    fields_json: str


def fake_message(fields, config):
    """Same shape as MAVSDK MavlinkMessage, without MAVSDK."""

    return Msg(
        "COMMAND_LONG",
        config.ground_station_system_id,
        config.ground_station_component_id,
        int(fields["target_system"]),
        int(fields["target_component"]),
        json.dumps(fields),
    )


class FakeGroundLink:
    """Records what the sender hands to ``mavlink_direct.send_message``."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list = []
        self.fail = fail
        self.mavlink_direct = SimpleNamespace(send_message=self._send)

    async def _send(self, message) -> None:
        if self.fail:
            raise RuntimeError("link down")
        self.sent.append(message)


def run_ground_keys(keys, link, store, make_message=fake_message):
    out: list[str] = []

    async def run():
        lines: asyncio.Queue = asyncio.Queue()
        for key in keys:
            lines.put_nowait(key)
        await handle_ground_keys(lines, link, store, CONFIG, make_message, out.append)

    asyncio.run(run())
    return out


# ------------------------------------------------------------ endpoint guard
@pytest.mark.parametrize(
    "address",
    [
        "udpin://0.0.0.0:14550",
        "udpin://192.168.1.20:14550",
        "udp://:14550",
        "udpin://127.0.0.1:14540",  # the companion's port, not the ground port
        "serial:///dev/ttyUSB0:57600",
        "tcp://127.0.0.1:5760",
    ],
)
def test_sender_refuses_non_sitl_ground_addresses(address, tmp_path) -> None:
    with pytest.raises(ValueError, match="simulation-only"):
        require_sitl_ground_address(address)
    store_file = tmp_path / "seq.json"
    with pytest.raises(ValueError, match="simulation-only"):
        asyncio.run(run_sender(address, store_file, CONFIG))
    assert not store_file.exists()  # no sequence reserved before the guard


def test_sender_accepts_local_sitl_ground_port() -> None:
    assert require_sitl_ground_address("udpin://127.0.0.1:14550")


def test_sender_refuses_corrupt_sequence_file_before_connecting(tmp_path) -> None:
    store_file = tmp_path / "seq.json"
    store_file.write_text("not json", encoding="utf-8")
    with pytest.raises(GrantSequenceError):
        asyncio.run(run_sender("udpin://127.0.0.1:14550", store_file, CONFIG))


# ---------------------------------------------------------------- sending
def test_grants_increment_and_revoke_uses_no_sequence(tmp_path) -> None:
    store = GrantSequenceStore(tmp_path / "seq.json")
    link = FakeGroundLink()
    out = run_ground_keys(["g\n", "g\n", "r\n", "x\n", "q\n", "g\n"], link, store)
    assert store.last() == 2  # nothing after q is sent
    params = [json.loads(m.fields_json) for m in link.sent]
    assert [(p["param1"], p["param2"]) for p in params] == [(1.0, 1.0), (1.0, 2.0), (2.0, 0.0)]
    assert all((m.target_system_id, m.target_component_id) == (1, 191) for m in link.sent)
    assert out[0].startswith("grant #1 sent") and out[2].startswith("revoke sent")
    assert out[3].startswith("keys:")


def test_failed_send_is_reported_and_skips_that_sequence(tmp_path) -> None:
    store = GrantSequenceStore(tmp_path / "seq.json")
    out = run_ground_keys(["g\n", None], FakeGroundLink(fail=True), store)
    assert "send failed (RuntimeError: link down); not retried" in out[0]
    assert store.last() == 1  # reserved before sending: never reused

    link = FakeGroundLink()
    assert asyncio.run(send_grant(link, store, CONFIG, fake_message)) == 2


def test_real_mavsdk_message_carries_ground_ids_and_target() -> None:
    pytest.importorskip("mavsdk")
    from coyote.ground.grant_sender import grant_command_fields

    message = command_message(grant_command_fields(7, CONFIG), CONFIG)
    assert message.message_name == "COMMAND_LONG"
    assert (message.system_id, message.component_id) == (255, 190)
    assert (message.target_system_id, message.target_component_id) == (1, 191)


# ------------------------------------- end to end through the watch facade
def healthy(tracker: TelemetryTracker, t: float) -> None:
    tracker.update_flight_mode("HOLD", t)
    tracker.update_armed(False, t)
    tracker.update_in_air(False, t)
    tracker.update_position(0.0, t)
    tracker.update_battery_percent(90.0, t)
    tracker.update_failsafe(False, t)


def test_sent_commands_reach_authority_through_the_watch_facade(tmp_path) -> None:
    """Ground sender output fed to the companion side unchanged (no PX4 in between)."""

    store = GrantSequenceStore(tmp_path / "seq.json")
    link = FakeGroundLink()
    run_ground_keys(["g\n", "r\n", "g\n", None], link, store)
    replayed = link.sent[0]  # a retransmitted first grant at the end
    stream = [*link.sent, replayed]

    clock = Clock(10.0)
    tracker = TelemetryTracker()
    authority = DelegationAuthority()
    log = ObservationLog(started_s=10.0)

    async def messages(_name):
        for message in stream:
            healthy(tracker, clock.t)
            observe_vehicle(tracker, authority, clock.t)
            yield message
            clock.t += 0.1
        await asyncio.Event().wait()  # stream stays open

    drone = SimpleNamespace(
        telemetry=SimpleNamespace(), mavlink_direct=SimpleNamespace(message=messages)
    )
    facade = observing_drone(drone, log, clock, HeartbeatSourceConfig())

    async def run():
        errors: dict = {}
        task = subscribe_ground_commands(
            facade, authority, clock, errors, CONFIG, command_reporter(log)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return errors

    errors = asyncio.run(run())
    assert errors == {}
    texts = [text for _, text in log.events]
    assert texts[0].startswith("ground command grant #1") and "accepted=True" in texts[0]
    assert texts[1].startswith("ground command revoke")
    assert texts[2].startswith("ground command grant #2") and "accepted=True" in texts[2]
    assert texts[3].startswith("ground command grant #1") and "accepted=False" in texts[3]
    assert authority.delegated(clock.t)  # the replayed grant changed nothing
    assert log.message_counts["command_long"] == 4
    assert log.message_counts["autopilot_heartbeat"] == 0  # not mistaken for heartbeats


def test_command_stream_end_revokes_with_command_link_lost() -> None:
    clock = Clock(1.0)
    tracker, authority = TelemetryTracker(), DelegationAuthority()
    healthy(tracker, 1.0)
    observe_vehicle(tracker, authority, 1.0)
    assert authority.request_grant(GrantCommand(1, 1.0), 1.0).accepted

    async def nothing(_name):
        return
        yield

    drone = SimpleNamespace(
        telemetry=SimpleNamespace(), mavlink_direct=SimpleNamespace(message=nothing)
    )
    facade = observing_drone(drone, ObservationLog(0.0), clock, HeartbeatSourceConfig())
    errors: dict = {}

    async def run():
        await subscribe_ground_commands(facade, authority, clock, errors, CONFIG)

    asyncio.run(run())
    assert errors[COMMAND_SOURCE_KEY] == "stream ended"
    assert not authority.delegated(1.0)
    assert authority.drain_alerts()[-1].reason is RevocationReason.COMMAND_LINK_LOST


# ------------------------------------------------------------ watch options
def test_grant_key_is_disabled_in_mavlink_mode(capsys) -> None:
    clock, authority = Clock(1.0), DelegationAuthority()
    log = ObservationLog(0.0)

    async def run():
        lines: asyncio.Queue = asyncio.Queue()
        for key in ("g\n", "r\n", None):
            lines.put_nowait(key)
        await handle_keys(lines, authority, log, clock, asyncio.Event(), False)

    asyncio.run(run())
    assert "g disabled" in capsys.readouterr().out
    assert [text for _, text in log.events] == ["operator revoke requested"]


def test_watch_grant_source_option() -> None:
    assert parse_args([]).grant_source == "keyboard"
    assert parse_args(["--grant-source", "mavlink"]).grant_source == "mavlink"
    with pytest.raises(SystemExit):
        parse_args(["--grant-source", "radio"])


def test_watch_rejects_unknown_grant_source_before_connecting() -> None:
    with pytest.raises(ValueError, match="grant source"):
        asyncio.run(
            run_watch(SitlMissionConfig(), 10.0, False, HeartbeatSourceConfig(), None, "radio")
        )


def test_watch_mavlink_mode_still_refuses_non_sitl_endpoint() -> None:
    config = SitlMissionConfig(system_address="udpin://0.0.0.0:14540")
    with pytest.raises(ValueError, match="simulation-only"):
        asyncio.run(run_watch(config, 10.0, False, HeartbeatSourceConfig(), None, "mavlink"))
