"""Ground-side R6 grant sender: sequence store and COMMAND_LONG fields."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from coyote.autonomy.action_gate import VehicleSnapshot
from coyote.autonomy.delegation import DelegationAuthority
from coyote.autonomy.grant_transport import (
    MAX_SEQUENCE,
    GrantTransportConfig,
    GroundCommandKind,
    apply_ground_command,
    decode_ground_command,
)
from coyote.ground.grant_sender import (
    GrantSequenceError,
    GrantSequenceStore,
    grant_command_fields,
    next_grant_fields,
    revoke_command_fields,
)

CFG = GrantTransportConfig()
ON_GROUND_ARMED = VehicleSnapshot(
    flight_mode="HOLD",
    armed=True,
    in_air=False,
    relative_altitude_m=0.0,
    battery_remaining_fraction=1.0,
    telemetry_age_s=0.1,
)


def as_message(fields, source=(255, 190)):
    return SimpleNamespace(
        message_name="COMMAND_LONG",
        system_id=source[0],
        component_id=source[1],
        fields_json=json.dumps(fields),
    )


def test_sequence_starts_at_one_and_strictly_increases(tmp_path) -> None:
    store = GrantSequenceStore(tmp_path / "grant_seq.json")
    assert store.last() == 0
    assert [store.next() for _ in range(3)] == [1, 2, 3]


def test_sequence_survives_a_restart_of_the_ground_tool(tmp_path) -> None:
    path = tmp_path / "grant_seq.json"
    GrantSequenceStore(path).next()
    GrantSequenceStore(path).next()
    assert GrantSequenceStore(path).next() == 3


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        '{"last_sequence": -1}',
        '{"last_sequence": 1.5}',
        '{"last_sequence": true}',
        json.dumps({"last_sequence": MAX_SEQUENCE + 1}),
    ],
)
def test_untrusted_sequence_file_raises_instead_of_guessing(tmp_path, content) -> None:
    path = tmp_path / "grant_seq.json"
    path.write_text(content)
    with pytest.raises(GrantSequenceError):
        GrantSequenceStore(path).next()
    assert path.read_text() == content  # left untouched


def test_exhausted_range_raises(tmp_path) -> None:
    path = tmp_path / "grant_seq.json"
    path.write_text(json.dumps({"last_sequence": MAX_SEQUENCE}))
    with pytest.raises(GrantSequenceError, match="used up"):
        GrantSequenceStore(path).next()


def test_grant_fields_decode_as_a_grant_on_the_companion(tmp_path) -> None:
    sequence, fields = next_grant_fields(GrantSequenceStore(tmp_path / "s.json"))
    command = decode_ground_command(as_message(fields), CFG)
    assert command.kind is GroundCommandKind.GRANT and command.sequence == sequence == 1


def test_revoke_fields_decode_as_a_revoke() -> None:
    command = decode_ground_command(as_message(revoke_command_fields()), CFG)
    assert command.kind is GroundCommandKind.REVOKE


def test_largest_sequence_round_trips_exactly() -> None:
    command = decode_ground_command(as_message(grant_command_fields(MAX_SEQUENCE)), CFG)
    assert command.sequence == MAX_SEQUENCE


@pytest.mark.parametrize("bad", [0, -1, MAX_SEQUENCE + 1, 1.0, True])
def test_bad_sequence_is_not_encoded(bad) -> None:
    with pytest.raises(ValueError):
        grant_command_fields(bad)


def test_custom_ids_match_between_sender_and_companion() -> None:
    cfg = GrantTransportConfig(companion_system_id=2, companion_component_id=192)
    command = decode_ground_command(as_message(grant_command_fields(5, cfg)), cfg)
    assert command.kind is GroundCommandKind.GRANT
    # The default companion config does not honour a command addressed elsewhere.
    assert decode_ground_command(as_message(grant_command_fields(5, cfg)), CFG).kind is (
        GroundCommandKind.REJECTED
    )


def test_regrant_after_revoke_is_accepted_by_the_companion(tmp_path) -> None:
    # Owner decision 2026-11-06: each send from the ground tool is a new command,
    # so grant -> revoke -> grant works (a fixed button would be refused as "not new").
    store = GrantSequenceStore(tmp_path / "s.json")
    auth = DelegationAuthority()
    auth.observe(ON_GROUND_ARMED, failsafe_active=False, now_s=10.0)

    def send(fields, now):
        return apply_ground_command(decode_ground_command(as_message(fields), CFG), auth, now)

    assert send(next_grant_fields(store)[1], 10.1).accepted
    send(revoke_command_fields(), 10.2)
    assert not auth.delegated(10.2)
    auth.observe(ON_GROUND_ARMED, failsafe_active=False, now_s=10.3)
    assert send(next_grant_fields(store)[1], 10.4).accepted and auth.delegated(10.4)
