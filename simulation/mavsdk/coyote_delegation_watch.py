"""Watch-only PX4 SITL run of the Coyote R6 delegation watch and failsafe source.

Simulation only. Refuses any vehicle endpoint other than the loopback SITL
listener (same guard as the smoke mission). This script **sends no flight
commands**: it never arms, takes off, changes mode, uploads or starts a
mission. The operator drives the simulated vehicle from the PX4 shell
(``commander ...``), standing in for the pilot and PX4 itself.

What it does:

1. Connects to PX4 SITL and starts the read-only Coyote telemetry pumps
   (``coyote.autonomy.vehicle_link``) and the candidate HEARTBEAT failsafe
   source (``coyote.autonomy.failsafe_source``).
2. Runs the R6 delegation watch. Its only outbound MAVLink is the
   ``STATUSTEXT`` revocation alert (``--no-status-text`` prints it instead).
3. Reads keyboard lines: ``g`` = local stand-in for the ground-station grant
   command, ``r`` = local operator revoke, ``q`` = quit. With
   ``--grant-source mavlink`` the ``g`` key is disabled and grants/revokes come
   only from the candidate MAVLink transport (``coyote.autonomy.grant_transport``),
   sent by ``simulation.mavsdk.coyote_ground_sender``; the watch then connects
   as the companion (default MAVLink id 1/191, a model input) so the command can
   be addressed to it. Either way a grant only changes local state; nothing is
   forwarded to PX4.
4. Prints a status line every second and every change, then a summary of what
   was observed: stream rates, the raw HEARTBEAT ``system_status`` values and
   their JSON form, failsafe mapping results and every revocation and alert.

The point is observation: to confirm or correct the unit-tested assumptions
(heartbeat rate, ``MAV_STATE`` during a PX4 failsafe, revocation latency,
whether QGroundControl shows the alert). A run of this script is not evidence
of anything until its output is recorded in a dated validation record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import threading
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from coyote.autonomy.command_link import CommandLink
from coyote.autonomy.delegation import DelegationAuthority, GrantCommand
from coyote.autonomy.failsafe_source import (
    HEARTBEAT_TRACKER_CONFIG,
    HeartbeatSourceConfig,
    failsafe_from_heartbeat,
    subscribe_failsafe_heartbeat,
)
from coyote.autonomy.grant_transport import (
    GrantTransportConfig,
    GroundCommand,
    subscribe_ground_commands,
)
from coyote.autonomy.ground_alerts import GroundAlertOutbox, StatusMessage
from coyote.autonomy.telemetry import TelemetryTracker
from coyote.autonomy.vehicle_link import (
    WatchConfig,
    WatchTick,
    mavsdk_status_text_sender,
    run_delegation_watch,
    subscribe_vehicle_telemetry,
)
from shared.autonomy.sitl import SitlMissionConfig, load_sitl_config
from simulation.mavsdk.smoke_mission import _wait_for_connection

STATUS_INTERVAL_S = 1.0
DEFAULT_DURATION_S = 900.0
TELEMETRY_STREAMS = ("flight_mode", "armed", "in_air", "position", "battery")
GRANT_SOURCES = ("keyboard", "mavlink", "command-link")
# PX4 SITL's second onboard MAVLink instance (px4-rc.mavlink: local 14280,
# remote 14030, forwarding on). Fixed and localhost-only: the command-link
# mode cannot be pointed anywhere else.
SITL_COMMAND_LINK_PX4 = ("127.0.0.1", 14280)
SITL_COMMAND_LINK_LOCAL = ("127.0.0.1", 14030)


# ----------------------------------------------------------- observation log
@dataclass
class ObservationLog:
    """Dependency-free record of what the watch saw. Times are monotonic seconds."""

    started_s: float
    message_counts: Counter = field(default_factory=Counter)
    first_s: dict = field(default_factory=dict)
    last_s: dict = field(default_factory=dict)
    heartbeat_sources: Counter = field(default_factory=Counter)
    system_status_values: Counter = field(default_factory=Counter)
    system_status_examples: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    def message(self, name: str, now_s: float) -> None:
        self.message_counts[name] += 1
        self.first_s.setdefault(name, now_s)
        self.last_s[name] = now_s

    def heartbeat(self, message: Any, now_s: float, config: HeartbeatSourceConfig) -> None:
        sysid = getattr(message, "system_id", None)
        compid = getattr(message, "component_id", None)
        self.heartbeat_sources[(sysid, compid)] += 1
        relevant, failsafe = failsafe_from_heartbeat(message, config)
        if not relevant:
            return
        self.message("autopilot_heartbeat", now_s)
        try:
            raw = json.loads(getattr(message, "fields_json", "")).get("system_status")
        except (TypeError, ValueError, AttributeError):
            raw = "<malformed>"
        key = repr(raw)
        if key not in self.system_status_values:
            self.event(now_s, f"autopilot system_status {key} -> failsafe {failsafe}")
            self.system_status_examples[key] = getattr(message, "fields_json", "")
        self.system_status_values[key] += 1

    def event(self, now_s: float, text: str) -> None:
        self.events.append((now_s - self.started_s, text))
        print(f"[{now_s - self.started_s:8.2f}s] {text}", flush=True)

    def rate_hz(self, name: str) -> float | None:
        n = self.message_counts.get(name, 0)
        if n < 2:
            return None
        span = self.last_s[name] - self.first_s[name]
        return (n - 1) / span if span > 0 else None

    def summary_lines(self) -> list[str]:
        lines = ["Stream messages (count, mean rate):"]
        for name in (*TELEMETRY_STREAMS, "autopilot_heartbeat", "command_long"):
            rate = self.rate_hz(name)
            shown = f"{rate:.2f} Hz" if rate is not None else "n/a"
            lines.append(f"  {name:20s} {self.message_counts.get(name, 0):6d}  {shown}")
        lines.append("HEARTBEAT senders (sysid, compid): count")
        for source, n in sorted(self.heartbeat_sources.items(), key=str):
            lines.append(f"  {source}: {n}")
        lines.append("Autopilot system_status values seen (raw JSON value: count):")
        for key, n in self.system_status_values.items():
            lines.append(f"  {key}: {n}   e.g. {self.system_status_examples[key]}")
        lines.append(f"Events: {len(self.events)} (listed above with times)")
        return lines


async def _counted(
    source: Callable[[], AsyncIterator[Any]],
    name: str,
    log: ObservationLog,
    clock: Callable[[], float],
) -> AsyncIterator[Any]:
    async for value in source():
        log.message(name, clock())
        yield value


def observing_drone(
    drone: Any,
    log: ObservationLog,
    clock: Callable[[], float],
    heartbeat_config: HeartbeatSourceConfig,
) -> Any:
    """Read-only facade: same streams as ``drone``, counted into ``log``.

    Exposes only ``telemetry.<five streams>`` and ``mavlink_direct.message``;
    no command plugin is reachable through it. ``HEARTBEAT`` messages are
    logged as heartbeats; ``COMMAND_LONG`` and any other subscribed message
    are only counted.
    """

    telemetry = SimpleNamespace(
        **{
            name: (lambda n=name: _counted(getattr(drone.telemetry, n), n, log, clock))
            for name in TELEMETRY_STREAMS
        }
    )

    async def direct_messages(message_name: str) -> AsyncIterator[Any]:
        async for message in drone.mavlink_direct.message(message_name):
            if message_name == "HEARTBEAT":
                log.heartbeat(message, clock(), heartbeat_config)
            else:
                log.message(message_name.lower(), clock())
            yield message

    return SimpleNamespace(
        telemetry=telemetry, mavlink_direct=SimpleNamespace(message=direct_messages)
    )


# ------------------------------------------------------------- status lines
def status_line(tracker: TelemetryTracker, authority: DelegationAuthority, now_s: float) -> str:
    snap = tracker.snapshot(now_s)
    battery = snap.battery_remaining_fraction
    battery_text = f"{battery * 100:.0f}%" if battery is not None else "?"
    age = snap.telemetry_age_s
    age_text = f"{age:.2f}s" if math.isfinite(age) else "inf"
    return (
        f"mode={snap.flight_mode} armed={snap.armed} in_air={snap.in_air} "
        f"alt={snap.relative_altitude_m:.1f}m batt={battery_text} age={age_text} "
        f"failsafe={tracker.failsafe_active(now_s)} delegated={authority.delegated(now_s)}"
    )


def command_reporter(log: ObservationLog) -> Callable[[float, GroundCommand, Any], None]:
    """Log every decoded ground command and what the authority did with it."""

    def on_command(now_s: float, command: GroundCommand, result: Any) -> None:
        sequence = f" #{command.sequence}" if command.sequence is not None else ""
        log.event(
            now_s,
            f"ground command {command.kind.value}{sequence} ({command.detail}): "
            f"accepted={result.accepted} ({result.reason})",
        )

    return on_command


def tick_reporter(log: ObservationLog, clock: Callable[[], float]) -> Callable[[WatchTick], None]:
    last = {"delegated": None}

    def on_tick(tick: WatchTick) -> None:
        now = clock()
        if tick.delegated != last["delegated"]:
            log.event(now, f"delegated -> {tick.delegated}")
            last["delegated"] = tick.delegated
        if tick.sent is not None:
            log.event(now, f"alert sent ({tick.sent.severity.name}): {tick.sent.text}")
        if tick.send_failed:
            log.event(now, f"alert send failed; {tick.pending_alerts} pending")

    return on_tick


def print_sender() -> Callable[[StatusMessage], Any]:
    async def send(message: StatusMessage) -> bool:
        print(f"(not sent, --no-status-text) {message.severity.name}: {message.text}")
        return True

    return send


def start_stdin_reader(loop: asyncio.AbstractEventLoop, lines: asyncio.Queue) -> None:
    """Read stdin in a daemon thread so a pending read never blocks exit."""

    def read() -> None:
        for line in sys.stdin:
            loop.call_soon_threadsafe(lines.put_nowait, line)
        loop.call_soon_threadsafe(lines.put_nowait, None)  # stdin closed

    threading.Thread(target=read, name="watch-keyboard", daemon=True).start()


async def handle_keys(
    lines: asyncio.Queue,
    authority: DelegationAuthority,
    log: ObservationLog,
    clock: Callable[[], float],
    stop: asyncio.Event,
    grant_from_keyboard: bool = True,
) -> None:
    """Apply operator keys. ``g`` is a local stand-in for the grant command and
    is disabled when grants come from the MAVLink transport."""

    sequence = 0
    while not stop.is_set():
        line = await lines.get()
        if line is None:
            return
        key = line.strip().lower()
        now = clock()
        if key == "g" and not grant_from_keyboard:
            print("g disabled: send the grant from coyote_ground_sender (--grant-source mavlink)")
        elif key == "g":
            sequence += 1
            result = authority.request_grant(GrantCommand(sequence, now), now)
            log.event(now, f"grant #{sequence}: accepted={result.accepted} ({result.reason})")
        elif key == "r":
            authority.revoke_by_operator(now)
            log.event(now, "operator revoke requested")
        elif key == "q":
            stop.set()
        elif key:
            print("keys: g = grant (local stand-in), r = revoke, q = quit")


async def _status_printer(
    tracker: TelemetryTracker,
    authority: DelegationAuthority,
    clock: Callable[[], float],
    stop: asyncio.Event,
    log: ObservationLog,
) -> None:
    while not stop.is_set():
        now = clock()
        print(f"[{now - log.started_s:8.2f}s] {status_line(tracker, authority, now)}", flush=True)
        await asyncio.sleep(STATUS_INTERVAL_S)


def open_sitl_command_link(transport: GrantTransportConfig) -> Any:
    """pymavlink connection to PX4 SITL's second onboard link, as the companion.

    Sends to 127.0.0.1:14280 from 127.0.0.1:14030 (where PX4 SITL sends that
    link's traffic). No other address is possible.
    """

    from pymavlink import mavutil  # imported here so unit tests need no pymavlink

    host, port = SITL_COMMAND_LINK_PX4
    conn = mavutil.mavlink_connection(
        f"udpout:{host}:{port}",
        source_system=transport.companion_system_id,
        source_component=transport.companion_component_id,
    )
    conn.port.bind(SITL_COMMAND_LINK_LOCAL)
    return conn


def counted_link(link: CommandLink, log: ObservationLog, clock: Callable[[], float]) -> Any:
    async def messages(message_name: str) -> AsyncIterator[Any]:
        async for message in link.messages(message_name):
            log.message(message_name.lower(), clock())
            yield message

    return SimpleNamespace(mavlink_direct=SimpleNamespace(message=messages))


def ack_reporter(log: ObservationLog) -> Callable[[float, dict, str | None], None]:
    def on_ack(now_s: float, fields: dict, error: str | None) -> None:
        outcome = "sent" if error is None else f"FAILED ({error})"
        log.event(
            now_s,
            f"COMMAND_ACK result={fields['result']} seq={fields['result_param2']} {outcome}",
        )

    return on_ack


# ----------------------------------------------------------------- main run
async def run_watch(
    config: SitlMissionConfig,
    duration_s: float,
    send_status_text: bool,
    heartbeat_config: HeartbeatSourceConfig,
    holder: dict | None = None,
    grant_source: str = "keyboard",
    transport_config: GrantTransportConfig | None = None,
) -> ObservationLog:
    """Watch until ``q``, stdin closes or ``duration_s``. ``holder['log']`` is
    set as soon as observation starts, so Ctrl+C can still print the summary."""

    config.validate()  # refuses non-loopback, wildcard and serial endpoints
    heartbeat_config.validate()
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("duration must be a positive number of seconds")
    if grant_source not in GRANT_SOURCES:
        raise ValueError(f"grant source must be one of {GRANT_SOURCES}")
    transport = transport_config or GrantTransportConfig()
    transport.validate()
    from mavsdk import System  # imported here so unit tests need no MAVSDK

    clock = time.monotonic
    if grant_source in ("mavlink", "command-link"):
        # Identify as the companion so the ground command can be addressed to it.
        drone = System(
            sysid=transport.companion_system_id, compid=transport.companion_component_id
        )
    else:
        drone = System()
    print(f"Connecting to PX4 SITL at {config.system_address} ...")
    await drone.connect(system_address=config.system_address)
    await _wait_for_connection(drone, config.connection_timeout_s)
    print("Connected. Watch only: this script sends no flight commands.")
    link = None
    if grant_source == "command-link":
        link = CommandLink(open_sitl_command_link(transport), transport)
        print(
            "Command link: listening as the companion on "
            f"{SITL_COMMAND_LINK_LOCAL[0]}:{SITL_COMMAND_LINK_LOCAL[1]} "
            "(PX4 SITL second onboard link)"
        )
    if grant_source != "keyboard":
        print(
            "Grants come from coyote_ground_sender (MAVLink). "
            "Keys + Enter: r = local revoke, q = quit"
        )
    else:
        print("Keys + Enter: g = grant (local stand-in), r = revoke, q = quit")

    log = ObservationLog(started_s=clock())
    if holder is not None:
        holder["log"] = log
    tracker = TelemetryTracker(HEARTBEAT_TRACKER_CONFIG)
    authority = DelegationAuthority()
    outbox = GroundAlertOutbox()
    stream_errors: dict = {}
    facade = observing_drone(drone, log, clock, heartbeat_config)
    stop = asyncio.Event()

    tasks = subscribe_vehicle_telemetry(facade, tracker, clock, stream_errors)
    tasks.append(
        subscribe_failsafe_heartbeat(facade, tracker, clock, stream_errors, heartbeat_config)
    )
    if grant_source == "mavlink":
        tasks.append(
            subscribe_ground_commands(
                facade, authority, clock, stream_errors, transport, command_reporter(log)
            )
        )
    elif link is not None:
        tasks.append(
            subscribe_ground_commands(
                counted_link(link, log, clock),
                authority,
                clock,
                stream_errors,
                transport,
                command_reporter(log),
                send_ack=link.send_ack,
                on_ack=ack_reporter(log),
            )
        )
    sender = mavsdk_status_text_sender(drone) if send_status_text else print_sender()
    tasks.append(
        asyncio.create_task(
            run_delegation_watch(
                tracker,
                authority,
                outbox,
                sender,
                clock,
                WatchConfig(),
                on_tick=tick_reporter(log, clock),
            )
        )
    )
    tasks.append(asyncio.create_task(_status_printer(tracker, authority, clock, stop, log)))
    lines: asyncio.Queue = asyncio.Queue()
    start_stdin_reader(asyncio.get_running_loop(), lines)
    tasks.append(
        asyncio.create_task(
            handle_keys(lines, authority, log, clock, stop, grant_source == "keyboard")
        )
    )
    try:
        await asyncio.wait_for(stop.wait(), timeout=duration_s)
    except TimeoutError:
        log.event(clock(), f"duration {duration_s:.0f}s reached")
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if stream_errors:
        log.event(clock(), f"stream problems: {stream_errors}")
    return log


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description="Coyote R6 watch-only PX4 SITL observation")
    parser.add_argument("--config", type=Path, default=here / "sitl_config.json")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument(
        "--no-status-text",
        action="store_true",
        help="print revocation alerts instead of sending them as STATUSTEXT",
    )
    parser.add_argument(
        "--grant-source",
        choices=GRANT_SOURCES,
        default="keyboard",
        help=(
            "keyboard: 'g' stand-in (default); mavlink: COMMAND_LONG via the MAVSDK link "
            "(received nothing in SITL 2026-11-08); command-link: COMMAND_LONG on PX4 "
            "SITL's second onboard link with COMMAND_ACK replies"
        ),
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    config = load_sitl_config(args.config)
    holder: dict = {}
    try:
        asyncio.run(
            run_watch(
                config,
                args.duration,
                not args.no_status_text,
                HeartbeatSourceConfig(),
                holder,
                grant_source=args.grant_source,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted (Ctrl+C); summary so far:")
    if "log" in holder:
        print("\n".join(holder["log"].summary_lines()))
    print("OBSERVATION ONLY: record this output in a dated validation record; it is not a PASS.")


if __name__ == "__main__":
    main()
