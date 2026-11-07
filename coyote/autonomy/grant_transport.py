"""Candidate R6 grant/revoke transport: a MAVLink ``COMMAND_LONG`` to the Jetson.

R6 (owner decisions 2026-10-18 and 2026-10-20) says companion authority is
granted by a ground-station command and returns only when the operator
re-sends it. :class:`~coyote.autonomy.delegation.DelegationAuthority` already
implements the rule, but nothing carried the operator's command to it: the
SITL watch script used a keyboard stand-in. This module is a **candidate**
transport (implementation choice, not an owner requirement) so that the grant
path can be exercised end to end in SITL.

Encoding (implementation choice; every number is a MODEL INPUT)
---------------------------------------------------------------
A ``COMMAND_LONG`` from the ground station, addressed to the companion
component, with:

* ``command`` = :attr:`GrantTransportConfig.command_id` (default
  ``MAV_CMD_USER_1`` = 31010, a MAVLink user-defined command that PX4 does not
  act on);
* ``param1`` = :data:`ACTION_GRANT` (1) or :data:`ACTION_REVOKE` (2); any other
  value is rejected, so an all-zero or garbled command does nothing;
* ``param2`` = the ground station's grant sequence number, a whole number from
  1 to 2**24 (exact in a MAVLink float32). The authority refuses any sequence
  that is not greater than every sequence it has seen, so the ground tool must
  increment it on every grant. A revoke does not need a sequence.

Only messages whose source is the configured ground station and whose target is
the configured companion system/component are honoured. Commands with the
right command id but the wrong source or target, a bad action code or a bad
sequence are returned as ``REJECTED`` (with the reason, for the log) and never
change delegation state. Broadcast targets (0) are rejected.

What this does **not** establish
--------------------------------
* The receive time on the companion clock is used as ``issued_at_s``: there
  is no shared clock with the ground station, so the authority's grant-age
  limit only bounds local processing delay here. Replay protection rests on
  the sequence rule and on the authority's fresh-observation checks.
* Whether PX4 forwards a ground-station ``COMMAND_LONG`` to the companion link
  (PX4 ``MAV_*_FORWARD`` settings), whether MAVSDK's ``mavlink_direct`` plugin
  delivers it to the Jetson, and whether MAVSDK itself answers it are **not
  observed**. The default ids (ground station 255/190, companion 1/191) are
  common MAVLink conventions, not Coyote parameters; they must match the
  ground tool and the MAVSDK configuration actually used.
* A ``COMMAND_ACK`` reply is a **candidate** (:func:`command_ack_fields`,
  :func:`mavsdk_ack_sender`, the ``send_ack`` hook of
  :func:`pump_ground_commands`); it is not wired into any script yet. Without
  it a ground tool may retransmit. A retransmitted grant reuses its sequence
  and is refused as "not new" without changing state; the first copy's result
  stands.
* Ground tool (owner decision 2026-11-06): a small ground-side script/app
  that increments the sequence on every grant; a fixed QGroundControl button
  is not used. Its sequence keeping and message fields are in
  :mod:`coyote.ground.grant_sender`; the MAVLink send itself is not written.

If the ``COMMAND_LONG`` subscription ends or raises, the operator can no longer
revoke through this channel, so delegation is revoked with
``COMMAND_LINK_LOST`` (implementation choice; sticky like every revocation).

Authority boundary: nothing here commands the vehicle. The only message this
module can send is the optional ``COMMAND_ACK`` reply to the ground station.
A grant only sets the companion's ``operator_delegated`` flag through the
authority, which still refuses it unless PX4 state is fresh, failsafe-free and
not pilot- or recovery-controlled. Unit-tested only.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from coyote.autonomy.delegation import DelegationAuthority, GrantCommand, GrantResult

MAV_CMD_USER_1 = 31010
ACTION_GRANT = 1
ACTION_REVOKE = 2
MAX_SEQUENCE = 2**24  # largest run of integers a float32 param holds exactly
COMMAND_SOURCE_KEY = "ground_command"


@dataclass(frozen=True)
class GrantTransportConfig:
    """MODEL INPUTS: MAVLink identities and command id. Not Coyote parameters.

    Defaults: ground station system 255 / component 190
    (``MAV_COMP_ID_MISSIONPLANNER``, used by common ground stations), companion
    addressed as system 1 (PX4's default ``MAV_SYS_ID``) / component 191
    (``MAV_COMP_ID_ONBOARD_COMPUTER``), command ``MAV_CMD_USER_1``.
    """

    ground_station_system_id: int = 255
    ground_station_component_id: int = 190
    companion_system_id: int = 1
    companion_component_id: int = 191
    command_id: int = MAV_CMD_USER_1

    def validate(self) -> None:
        for name in (
            "ground_station_system_id",
            "ground_station_component_id",
            "companion_system_id",
            "companion_component_id",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 255:
                raise ValueError(f"{name} must be an integer from 1 to 255")
        cmd = self.command_id
        if isinstance(cmd, bool) or not isinstance(cmd, int) or not 0 <= cmd <= 65535:
            raise ValueError("command_id must be an integer from 0 to 65535")


class GroundCommandKind(Enum):
    GRANT = "grant"
    REVOKE = "revoke"
    REJECTED = "rejected"


@dataclass(frozen=True)
class GroundCommand:
    kind: GroundCommandKind
    sequence: int | None = None
    detail: str = ""
    # False when the message came from an unexpected source or was addressed to
    # someone else (including broadcast): the companion does not answer those.
    ackable: bool = True


def _whole_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def decode_ground_command(
    message: Any, config: GrantTransportConfig | None = None
) -> GroundCommand | None:
    """Interpret one MAVSDK ``MavlinkMessage``.

    Returns ``None`` when the message is not a ``COMMAND_LONG`` with the
    configured command id (not ours, ignore silently). Otherwise returns a
    GRANT, REVOKE or REJECTED command; REJECTED carries the reason.
    """

    cfg = config or GrantTransportConfig()
    if getattr(message, "message_name", None) != "COMMAND_LONG":
        return None
    try:
        fields = json.loads(getattr(message, "fields_json", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(fields, dict) or _whole_number(fields.get("command")) != cfg.command_id:
        return None

    def reject(detail: str, ackable: bool = True) -> GroundCommand:
        return GroundCommand(GroundCommandKind.REJECTED, None, detail, ackable)

    source = (getattr(message, "system_id", None), getattr(message, "component_id", None))
    if source != (cfg.ground_station_system_id, cfg.ground_station_component_id):
        return reject(f"command from unexpected source {source[0]}/{source[1]}", False)
    target = (
        _whole_number(fields.get("target_system")),
        _whole_number(fields.get("target_component")),
    )
    if target != (cfg.companion_system_id, cfg.companion_component_id):
        return reject(f"command addressed to {target[0]}/{target[1]}, not the companion", False)

    action = _whole_number(fields.get("param1"))
    if action == ACTION_REVOKE:
        return GroundCommand(GroundCommandKind.REVOKE, None, "operator revoke")
    if action != ACTION_GRANT:
        return reject(f"unknown action {fields.get('param1')!r}")
    sequence = _whole_number(fields.get("param2"))
    if sequence is None or not 1 <= sequence <= MAX_SEQUENCE:
        return reject(f"grant sequence {fields.get('param2')!r} is not a whole number 1..2**24")
    return GroundCommand(GroundCommandKind.GRANT, sequence, "operator grant")


def apply_ground_command(
    command: GroundCommand, authority: DelegationAuthority, now_s: float
) -> GrantResult:
    """Pass a decoded command to the authority. REJECTED changes nothing."""

    if command.kind is GroundCommandKind.GRANT:
        if command.sequence is None:
            return GrantResult(False, "grant without a sequence")
        return authority.request_grant(GrantCommand(command.sequence, now_s), now_s)
    if command.kind is GroundCommandKind.REVOKE:
        authority.revoke_by_operator(now_s)
        return GrantResult(False, "delegation revoked by operator")
    return GrantResult(False, f"command rejected: {command.detail}")


# MAVLink MAV_RESULT values used in the reply (common.xml).
MAV_RESULT_ACCEPTED = 0
MAV_RESULT_DENIED = 2
DEFAULT_ACK_TIMEOUT_S = 1.0  # MODEL INPUT / placeholder, like WatchConfig.send_timeout_s


def command_ack_fields(
    command: GroundCommand, result: GrantResult, config: GrantTransportConfig | None = None
) -> dict[str, int] | None:
    """``COMMAND_ACK`` fields answering one decoded command, or ``None``.

    Implementation choice (candidate, not an owner requirement):

    * accepted grant (including "already delegated") -> ``MAV_RESULT_ACCEPTED``;
    * refused grant (stale or ineligible vehicle, old sequence, ...) ->
      ``MAV_RESULT_DENIED``;
    * revoke -> ``MAV_RESULT_ACCEPTED``: the companion is not delegated after
      it, whatever it was before;
    * a command rejected while decoding (bad action or sequence) ->
      ``MAV_RESULT_DENIED``;
    * a command from an unexpected source or addressed elsewhere -> ``None``,
      no reply.

    ``result_param2`` echoes the grant sequence (0 when there is none) so the
    ground tool can tell this reply apart from any other ``COMMAND_ACK`` for
    the same command id. The reply describes the moment the command was
    handled; it does not say that delegation is still in force later.
    Revocations are reported separately by the STATUSTEXT alerts.
    """

    cfg = config or GrantTransportConfig()
    if not command.ackable:
        return None
    if command.kind is GroundCommandKind.GRANT:
        code = MAV_RESULT_ACCEPTED if result.accepted else MAV_RESULT_DENIED
    elif command.kind is GroundCommandKind.REVOKE:
        code = MAV_RESULT_ACCEPTED
    else:
        code = MAV_RESULT_DENIED
    return {
        "command": cfg.command_id,
        "result": code,
        "progress": 0,
        "result_param2": command.sequence or 0,
        "target_system": cfg.ground_station_system_id,
        "target_component": cfg.ground_station_component_id,
    }


AckSender = Callable[[dict[str, int]], Awaitable[None]]


def mavsdk_ack_sender(drone: Any, config: GrantTransportConfig | None = None) -> AckSender:
    """Send ``COMMAND_ACK`` fields through MAVSDK 3.x ``mavlink_direct.send_message``.

    The message carries the companion's configured ids as its source. Whether
    MAVSDK sends it with those ids, whether PX4 forwards it to the ground link
    and whether MAVSDK also answers the ``COMMAND_LONG`` itself are **not
    observed**. ``send_message`` raises on failure; the pump records that.
    """

    cfg = config or GrantTransportConfig()
    cfg.validate()

    async def send(fields: dict[str, int]) -> None:
        from mavsdk.mavlink_direct import MavlinkMessage  # unit tests need no MAVSDK

        await drone.mavlink_direct.send_message(
            MavlinkMessage(
                "COMMAND_ACK",
                cfg.companion_system_id,
                cfg.companion_component_id,
                int(fields["target_system"]),
                int(fields["target_component"]),
                json.dumps(fields),
            )
        )

    return send


CommandLogger = Callable[[float, GroundCommand, GrantResult], None]
AckLogger = Callable[[float, dict[str, int], str | None], None]


async def _send_ack(
    send_ack: AckSender,
    fields: dict[str, int],
    timeout_s: float,
    clock: Callable[[], float],
    on_ack: AckLogger | None,
) -> None:
    """One bounded send attempt. Failure is reported, never retried, never revokes."""

    error: str | None = None
    try:
        await asyncio.wait_for(send_ack(fields), timeout_s)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        error = f"ack send timed out after {timeout_s:g} s"
    except Exception as exc:  # report and carry on; delegation state is already set
        error = f"{type(exc).__name__}: {exc}"
    if on_ack is not None:
        on_ack(clock(), fields, error)


async def pump_ground_commands(
    drone: Any,
    authority: DelegationAuthority,
    clock: Callable[[], float],
    stream_errors: dict[Any, str],
    config: GrantTransportConfig | None = None,
    on_command: CommandLogger | None = None,
    send_ack: AckSender | None = None,
    ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S,
    on_ack: AckLogger | None = None,
) -> None:
    """Feed ``authority`` from ``drone.mavlink_direct`` ``COMMAND_LONG`` messages.

    ``on_command(now, command, result)`` is called for every grant, revoke or
    rejected command (for logging). If the stream ends or raises, the reason is
    stored under :data:`COMMAND_SOURCE_KEY` and the authority revokes with
    ``COMMAND_LINK_LOST``.

    Without ``send_ack`` this is read-only. With it, each answerable command
    gets one ``COMMAND_ACK`` attempt **after** the authority has handled it,
    bounded by ``ack_timeout_s``; ``on_ack(now, fields, error)`` reports the
    outcome (``error`` is ``None`` when the transport accepted it). A failed or
    slow reply never changes delegation state and is not retried; a slow reply
    can delay handling of the next command by at most ``ack_timeout_s``.
    """

    cfg = config or GrantTransportConfig()
    cfg.validate()
    if not (math.isfinite(ack_timeout_s) and ack_timeout_s > 0.0):
        raise ValueError("ack_timeout_s must be a positive finite number")
    try:
        async for message in drone.mavlink_direct.message("COMMAND_LONG"):
            command = decode_ground_command(message, cfg)
            if command is None:
                continue
            now = clock()
            result = apply_ground_command(command, authority, now)
            if on_command is not None:
                on_command(now, command, result)
            if send_ack is not None:
                fields = command_ack_fields(command, result, cfg)
                if fields is not None:
                    await _send_ack(send_ack, fields, ack_timeout_s, clock, on_ack)
        reason = "stream ended"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # the channel is gone either way; record and revoke
        reason = f"{type(exc).__name__}: {exc}"
    stream_errors[COMMAND_SOURCE_KEY] = reason
    authority.revoke_command_link_lost(f"ground command stream: {reason}", clock())


def subscribe_ground_commands(
    drone: Any,
    authority: DelegationAuthority,
    clock: Callable[[], float],
    stream_errors: dict[Any, str],
    config: GrantTransportConfig | None = None,
    on_command: CommandLogger | None = None,
    send_ack: AckSender | None = None,
    ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S,
    on_ack: AckLogger | None = None,
) -> asyncio.Task:
    """Start :func:`pump_ground_commands` as a task. Caller cancels it."""

    return asyncio.create_task(
        pump_ground_commands(
            drone, authority, clock, stream_errors, config, on_command,
            send_ack, ack_timeout_s, on_ack,
        )
    )
