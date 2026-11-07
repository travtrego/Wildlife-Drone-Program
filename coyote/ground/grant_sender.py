"""Ground-side half of the R6 grant command: sequence keeping and message fields.

Owner decision 2026-11-06 (PR #29): the R6 grant is sent by a small
ground-side script/app that increments the grant sequence on every send, so
the companion's "new command only" rule (``DelegationAuthority``) stays in
force. A fixed QGroundControl button is not used because it cannot change the
sequence.

This module is the deterministic part of that tool:

* :class:`GrantSequenceStore` keeps the last sequence in a small JSON file on
  the ground computer and hands out the next one. The new value is written
  (atomically) **before** it is returned, so a crash between "write" and
  "send" only skips a number; it never reuses one. A missing file starts at 1;
  an unreadable or out-of-range file raises instead of guessing, because a
  guessed lower number would just be refused by the companion.
* :func:`grant_command_fields` / :func:`revoke_command_fields` build the
  ``COMMAND_LONG`` fields that :func:`coyote.autonomy.grant_transport.decode_ground_command`
  accepts (same command id, action codes and target as
  :class:`~coyote.autonomy.grant_transport.GrantTransportConfig`).

* :func:`interpret_grant_ack` reads the companion's candidate ``COMMAND_ACK``
  reply (:func:`coyote.autonomy.grant_transport.command_ack_fields`) and says
  whether it confirms or refuses the command just sent. A reply is matched
  only when it comes from the configured companion, is addressed to this
  ground station, names the grant command id and echoes the expected
  sequence; anything else is ``UNMATCHED`` and must not be shown as a
  confirmation. No reply at all means "unknown", never "granted".

Not here, on purpose: opening a MAVLink connection and sending. The ground
tool's link, its MAVLink system/component id (must match the companion's
configured ground-station id, default 255/190) and whether PX4 forwards the
command to the companion are unobserved; that is the next SITL step and must
stay loopback-only. Nothing in this module sends, arms or commands anything.
Unit-tested only.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from coyote.autonomy.grant_transport import (
    ACTION_GRANT,
    ACTION_REVOKE,
    MAV_RESULT_ACCEPTED,
    MAX_SEQUENCE,
    GrantTransportConfig,
)


class GrantSequenceError(RuntimeError):
    """The sequence file cannot be trusted or the sequence range is used up."""


class GrantSequenceStore:
    """Strictly increasing grant sequence persisted in ``path`` (JSON)."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def last(self) -> int:
        """Last sequence handed out, or 0 if none has been."""

        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise GrantSequenceError(f"cannot read {self.path}: {exc}") from exc
        try:
            value = json.loads(text)["last_sequence"]
        except (ValueError, KeyError, TypeError) as exc:
            raise GrantSequenceError(f"{self.path} is not a grant sequence file") from exc
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_SEQUENCE:
            raise GrantSequenceError(f"{self.path} holds an invalid sequence {value!r}")
        return value

    def next(self) -> int:
        """Reserve and return the next sequence (written before it is returned)."""

        sequence = self.last() + 1
        if sequence > MAX_SEQUENCE:
            raise GrantSequenceError("grant sequence range used up (2**24)")
        self._write(sequence)
        return sequence

    def _write(self, sequence: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"last_sequence": sequence}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _base_fields(config: GrantTransportConfig, action: int) -> dict[str, float | int]:
    config.validate()
    return {
        "target_system": config.companion_system_id,
        "target_component": config.companion_component_id,
        "command": config.command_id,
        "confirmation": 0,
        "param1": float(action),
        "param2": 0.0,
        "param3": 0.0,
        "param4": 0.0,
        "param5": 0.0,
        "param6": 0.0,
        "param7": 0.0,
    }


def grant_command_fields(
    sequence: int, config: GrantTransportConfig | None = None
) -> dict[str, float | int]:
    """``COMMAND_LONG`` fields for a grant with ``sequence`` (1..2**24)."""

    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("grant sequence must be an integer")
    if not 1 <= sequence <= MAX_SEQUENCE:
        raise ValueError("grant sequence must be from 1 to 2**24")
    fields = _base_fields(config or GrantTransportConfig(), ACTION_GRANT)
    fields["param2"] = float(sequence)
    return fields


def revoke_command_fields(config: GrantTransportConfig | None = None) -> dict[str, float | int]:
    """``COMMAND_LONG`` fields for an operator revoke (no sequence needed)."""

    return _base_fields(config or GrantTransportConfig(), ACTION_REVOKE)


def next_grant_fields(
    store: GrantSequenceStore, config: GrantTransportConfig | None = None
) -> tuple[int, dict[str, float | int]]:
    """Reserve the next sequence and build its grant fields."""

    sequence = store.next()
    return sequence, grant_command_fields(sequence, config)


class AckOutcome(Enum):
    CONFIRMED = "confirmed"  # companion accepted the command when it handled it
    REFUSED = "refused"  # companion answered and did not accept it
    UNMATCHED = "unmatched"  # some other COMMAND_ACK; not an answer to this send


@dataclass(frozen=True)
class GrantAck:
    outcome: AckOutcome
    result: int | None
    detail: str


def _ack_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def interpret_grant_ack(
    message: Any, expected_sequence: int, config: GrantTransportConfig | None = None
) -> GrantAck | None:
    """Classify one MAVSDK ``MavlinkMessage`` against the command just sent.

    ``expected_sequence`` is the grant's sequence, or 0 for a revoke (the
    companion echoes 0 when a command has no sequence). Returns ``None`` when
    the message is not a ``COMMAND_ACK`` for the configured command id.

    ``CONFIRMED`` means the companion accepted the command at that moment. It
    does not mean delegation is still in force: the companion can revoke at
    any time and reports that through its STATUSTEXT alerts. A revoke reply is
    informational only, since the operator's revoke never depends on it.
    """

    cfg = config or GrantTransportConfig()
    cfg.validate()
    if isinstance(expected_sequence, bool) or not isinstance(expected_sequence, int):
        raise ValueError("expected_sequence must be an integer")
    if not 0 <= expected_sequence <= MAX_SEQUENCE:
        raise ValueError("expected_sequence must be from 0 (revoke) to 2**24")
    if getattr(message, "message_name", None) != "COMMAND_ACK":
        return None
    try:
        fields = json.loads(getattr(message, "fields_json", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(fields, dict) or _ack_int(fields.get("command")) != cfg.command_id:
        return None

    def unmatched(detail: str) -> GrantAck:
        return GrantAck(AckOutcome.UNMATCHED, _ack_int(fields.get("result")), detail)

    source = (getattr(message, "system_id", None), getattr(message, "component_id", None))
    if source != (cfg.companion_system_id, cfg.companion_component_id):
        return unmatched(f"reply from {source[0]}/{source[1]}, not the companion")
    target = (_ack_int(fields.get("target_system")), _ack_int(fields.get("target_component")))
    if target != (cfg.ground_station_system_id, cfg.ground_station_component_id):
        return unmatched(f"reply addressed to {target[0]}/{target[1]}, not this ground station")
    echoed = _ack_int(fields.get("result_param2"))
    if echoed != expected_sequence:
        return unmatched(f"reply for sequence {echoed!r}, expected {expected_sequence}")
    result = _ack_int(fields.get("result"))
    if result is None:
        return unmatched(f"reply result {fields.get('result')!r} is not a whole number")
    if result == MAV_RESULT_ACCEPTED:
        return GrantAck(AckOutcome.CONFIRMED, result, "companion accepted")
    return GrantAck(AckOutcome.REFUSED, result, f"companion refused (MAV_RESULT {result})")
