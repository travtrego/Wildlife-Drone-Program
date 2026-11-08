"""Candidate companion receive path for the R6 grant: a second, plain MAVLink link.

Why this exists (PX4 SIH SITL, 2026-11-08, ``docs/SITL_VALIDATION_2026-11-08_SIH.md``):
PX4 forwards the ground station's grant ``COMMAND_LONG`` (255/190 -> 1/191) to
its onboard links, but the companion's MAVSDK ``mavlink_direct`` subscription
delivered none of them; it appears to report only messages from the autopilot
system. A plain pymavlink connection on a second PX4 onboard link did receive
them. This module is that receive path, kept separate from the MAVSDK
telemetry connection.

:class:`CommandLink` wraps a pymavlink-like connection and offers:

* ``mavlink_direct.message(name)`` with the same message shape MAVSDK uses
  (``message_name``, ``system_id``, ``component_id``, ``fields_json``), so
  :func:`coyote.autonomy.grant_transport.pump_ground_commands` and
  :func:`~coyote.autonomy.grant_transport.decode_ground_command` work
  unchanged, with every source/target/sequence check they already apply;
* a 1 Hz companion ``HEARTBEAT`` (``MAV_TYPE_ONBOARD_CONTROLLER``). PX4 only
  forwards a message to a link where the target component has been seen
  (``component_was_seen`` in PX4's ``forward_message``), so without it the
  grant would never arrive;
* :meth:`CommandLink.send_ack` for the #33 ``COMMAND_ACK`` reply.

A receive error ends the stream, so the pump revokes with
``COMMAND_LINK_LOST``. A link that silently delivers nothing never produces a
grant, so authority simply stays off.

Authority boundary: the only messages sent are the companion heartbeat and the
``COMMAND_ACK`` reply. Nothing arms, takes off, changes mode or commands PX4.
Opening the connection is the caller's job; the SITL script restricts it to
localhost. On the real aircraft this needs a second Pixhawk-to-Jetson MAVLink
link (or a router) with PX4 forwarding enabled; that is unverified hardware
configuration, not decided here. Unit-tested with fakes; one SIH SITL session.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from coyote.autonomy.grant_transport import GrantTransportConfig

MAV_TYPE_ONBOARD_CONTROLLER = 18
MAV_AUTOPILOT_INVALID = 8
MAV_STATE_ACTIVE = 4


@dataclass(frozen=True)
class DirectMessage:
    """Same fields as MAVSDK 3.x ``mavlink_direct.MavlinkMessage`` that the decoders read."""

    message_name: str
    system_id: int
    component_id: int
    fields_json: str


def to_direct_message(message: Any) -> DirectMessage | None:
    """Convert a pymavlink message; ``None`` for parser placeholders (``BAD_DATA``)."""

    name = message.get_type()
    if name == "BAD_DATA":
        return None
    fields = {k: v for k, v in message.to_dict().items() if k != "mavpackettype"}
    return DirectMessage(
        name, int(message.get_srcSystem()), int(message.get_srcComponent()), json.dumps(fields)
    )


@dataclass(frozen=True)
class CommandLinkConfig:
    """MODEL INPUTS / placeholders."""

    heartbeat_interval_s: float = 1.0
    poll_timeout_s: float = 0.2

    def validate(self) -> None:
        for name in ("heartbeat_interval_s", "poll_timeout_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be a positive finite number")


class CommandLink:
    """Companion side of a plain MAVLink link carrying the R6 grant command."""

    def __init__(
        self,
        connection: Any,
        transport: GrantTransportConfig | None = None,
        config: CommandLinkConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._conn = connection
        self._transport = transport or GrantTransportConfig()
        self._transport.validate()
        mav = connection.mav
        ids = (getattr(mav, "srcSystem", None), getattr(mav, "srcComponent", None))
        expected = (self._transport.companion_system_id, self._transport.companion_component_id)
        if ids != expected:
            raise ValueError(f"connection sends as {ids[0]}/{ids[1]}, expected companion "
                             f"{expected[0]}/{expected[1]}")
        self._config = config or CommandLinkConfig()
        self._config.validate()
        self._clock = clock
        self._send_lock = threading.Lock()
        self._last_heartbeat_s: float | None = None
        self.mavlink_direct = SimpleNamespace(message=self.messages)

    def _send_heartbeat_if_due(self) -> None:
        now = self._clock()
        last = self._last_heartbeat_s
        if last is not None and now - last < self._config.heartbeat_interval_s:
            return
        with self._send_lock:
            self._conn.mav.heartbeat_send(
                MAV_TYPE_ONBOARD_CONTROLLER, MAV_AUTOPILOT_INVALID, 0, 0, MAV_STATE_ACTIVE
            )
        self._last_heartbeat_s = now

    async def messages(self, message_name: str) -> AsyncIterator[DirectMessage]:
        """Yield ``message_name`` messages; send the heartbeat while waiting.

        Exceptions from the connection propagate, ending the stream.
        """

        while True:
            self._send_heartbeat_if_due()
            raw = await asyncio.to_thread(
                self._conn.recv_match,
                type=message_name,
                blocking=True,
                timeout=self._config.poll_timeout_s,
            )
            if raw is None:
                continue
            message = to_direct_message(raw)
            if message is not None and message.message_name == message_name:
                yield message

    async def send_ack(self, fields: dict[str, int]) -> None:
        """Send ``COMMAND_ACK`` fields from ``command_ack_fields``."""

        def send() -> None:
            with self._send_lock:
                self._conn.mav.command_ack_send(
                    int(fields["command"]),
                    int(fields["result"]),
                    int(fields["progress"]),
                    int(fields["result_param2"]),
                    int(fields["target_system"]),
                    int(fields["target_component"]),
                )

        await asyncio.to_thread(send)
