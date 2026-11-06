"""SITL-only ground-side sender for the Coyote R6 grant/revoke command.

Simulation only. This plays the operator's ground tool (owner decision
2026-11-06: a ground-side script/app that increments the grant sequence on
every send, not a fixed QGroundControl button) against PX4 SITL, so the
companion's MAVLink grant path (``coyote_delegation_watch --grant-source
mavlink``) can be exercised end to end.

What it does:

1. Refuses any endpoint other than PX4 SITL's local ground-station port
   (``udpin://127.0.0.1:14550``; see :data:`SITL_GROUND_ADDRESSES`).
2. Connects to PX4 SITL as the configured ground station (MAVSDK system /
   component id from :class:`GrantTransportConfig`, default 255/190).
3. Reads keyboard lines: ``g`` reserves the next sequence from the sequence
   file and sends a grant ``COMMAND_LONG``; ``r`` sends a revoke; ``q`` quits.

The only MAVLink it sends itself is ``COMMAND_LONG`` ``MAV_CMD_USER_1``
addressed to the companion component (default 1/191), never to the autopilot
(1/1). It never arms, takes off, changes mode or uploads anything. MAVSDK also
sends its own ground-station heartbeat while connected.

"Sent" means MAVSDK accepted the message. Whether PX4 forwards it to the
companion link, and whether the companion's ``mavlink_direct`` subscription
receives it, is exactly what the SITL session must observe from the watch
script's output. A sequence is reserved before sending, so a failed send
skips that number (the companion refuses only reused or lower numbers).

Not evidence of anything until a run is recorded in a dated validation record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from coyote.autonomy.grant_transport import GrantTransportConfig
from coyote.ground.grant_sender import (
    GrantSequenceStore,
    next_grant_fields,
    revoke_command_fields,
)
from simulation.mavsdk.smoke_mission import _wait_for_connection

# PX4 SITL's default ground-station link sends to UDP 14550 on localhost
# (PX4 documentation; not observed with this script yet). Loopback only.
SITL_GROUND_ADDRESSES = frozenset(
    {
        "udpin://127.0.0.1:14550",
        "udpin://localhost:14550",
        "udp://127.0.0.1:14550",
        "udp://localhost:14550",
    }
)
DEFAULT_GROUND_ADDRESS = "udpin://127.0.0.1:14550"
# Outside the repository, so a test sequence never lands in Git.
DEFAULT_SEQUENCE_FILE = Path.home() / ".cache" / "wildlife-drone" / "sitl_grant_sequence.json"
CONNECTION_TIMEOUT_S = 30.0


def require_sitl_ground_address(address: str) -> str:
    """Return ``address`` if it is the local SITL ground port, else raise."""

    if address.strip().lower() not in SITL_GROUND_ADDRESSES:
        raise ValueError(
            f"Ground sender is simulation-only. Refusing non-SITL ground address: {address!r}"
        )
    return address


def command_message(fields: dict[str, float | int], config: GrantTransportConfig) -> Any:
    """Build a MAVSDK ``MavlinkMessage`` for ``COMMAND_LONG`` ``fields``."""

    from mavsdk.mavlink_direct import MavlinkMessage  # unit tests need no MAVSDK

    return MavlinkMessage(
        "COMMAND_LONG",
        config.ground_station_system_id,
        config.ground_station_component_id,
        int(fields["target_system"]),
        int(fields["target_component"]),
        json.dumps(fields),
    )


MessageFactory = Callable[[dict[str, float | int], GrantTransportConfig], Any]


async def send_grant(
    drone: Any,
    store: GrantSequenceStore,
    config: GrantTransportConfig,
    make_message: MessageFactory = command_message,
) -> int:
    """Reserve the next sequence, send the grant and return the sequence."""

    sequence, fields = next_grant_fields(store, config)
    await drone.mavlink_direct.send_message(make_message(fields, config))
    return sequence


async def send_revoke(
    drone: Any,
    config: GrantTransportConfig,
    make_message: MessageFactory = command_message,
) -> None:
    await drone.mavlink_direct.send_message(make_message(revoke_command_fields(config), config))


async def handle_ground_keys(
    lines: asyncio.Queue,
    drone: Any,
    store: GrantSequenceStore,
    config: GrantTransportConfig,
    make_message: MessageFactory = command_message,
    emit: Callable[[str], None] = print,
) -> None:
    """``g`` grant, ``r`` revoke, ``q`` quit. A failed send is reported, not retried."""

    while True:
        line = await lines.get()
        if line is None:
            return
        key = line.strip().lower()
        try:
            if key == "g":
                sequence = await send_grant(drone, store, config, make_message)
                emit(f"grant #{sequence} sent (MAVSDK accepted it; check the watch output)")
            elif key == "r":
                await send_revoke(drone, config, make_message)
                emit("revoke sent (MAVSDK accepted it; check the watch output)")
            elif key == "q":
                return
            elif key:
                emit("keys: g = grant (next sequence), r = revoke, q = quit")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # report and keep going; the operator decides
            emit(f"send failed ({type(exc).__name__}: {exc}); not retried")


def _start_stdin_reader(loop: asyncio.AbstractEventLoop, lines: asyncio.Queue) -> None:
    def read() -> None:
        for line in sys.stdin:
            loop.call_soon_threadsafe(lines.put_nowait, line)
        loop.call_soon_threadsafe(lines.put_nowait, None)

    threading.Thread(target=read, name="ground-keyboard", daemon=True).start()


async def run_sender(address: str, sequence_file: Path, config: GrantTransportConfig) -> None:
    require_sitl_ground_address(address)
    config.validate()
    store = GrantSequenceStore(sequence_file)
    store.last()  # refuse a corrupt sequence file before connecting
    from mavsdk import System  # imported here so unit tests need no MAVSDK

    drone = System(sysid=config.ground_station_system_id, compid=config.ground_station_component_id)
    print(
        f"Connecting to PX4 SITL ground port {address} as "
        f"{config.ground_station_system_id}/{config.ground_station_component_id} ..."
    )
    await drone.connect(system_address=address)
    await _wait_for_connection(drone, CONNECTION_TIMEOUT_S)
    print(
        f"Connected. Commands go to companion {config.companion_system_id}/"
        f"{config.companion_component_id}. Last sequence: {store.last()} ({sequence_file})"
    )
    print("Keys + Enter: g = grant (next sequence), r = revoke, q = quit")
    lines: asyncio.Queue = asyncio.Queue()
    _start_stdin_reader(asyncio.get_running_loop(), lines)
    await handle_ground_keys(lines, drone, store, config)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coyote R6 SITL-only ground grant sender")
    parser.add_argument("--address", default=DEFAULT_GROUND_ADDRESS)
    parser.add_argument("--sequence-file", type=Path, default=DEFAULT_SEQUENCE_FILE)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_sender(args.address, args.sequence_file, GrantTransportConfig()))
    except KeyboardInterrupt:
        print("\nInterrupted (Ctrl+C).")


if __name__ == "__main__":
    main()
