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

Not here, on purpose: opening a MAVLink connection and sending. The ground
tool's link, its MAVLink system/component id (must match the companion's
configured ground-station id, default 255/190) and whether PX4 forwards the
command to the companion are unobserved; that is the next SITL step and must
stay loopback-only. Nothing in this module sends, arms or commands anything.
Unit-tested only.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from coyote.autonomy.grant_transport import (
    ACTION_GRANT,
    ACTION_REVOKE,
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
