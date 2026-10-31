"""Wire MAVSDK telemetry and ground-station alerts to the R6 delegation authority.

The pieces already exist but nothing connects them to a vehicle or runs them
on a clock:

* :class:`~coyote.autonomy.telemetry.TelemetryTracker` expects "the future
  MAVSDK task" to call its ``update_*`` methods.
* :class:`~coyote.autonomy.delegation.DelegationAuthority` only revokes when
  something calls ``observe``/``delegated``. If the link goes silent and no
  companion request happens to arrive, nothing would notice, so R6's
  "revoked on telemetry-link loss, with a ground-station alert" would not
  happen in time.
* :class:`~coyote.autonomy.ground_alerts.GroundAlertOutbox` holds alerts but
  needs a transport and something that calls it.

This module provides those three missing links:

* :func:`subscribe_vehicle_telemetry` starts one **read-only** task per MAVSDK
  stream (flight mode, armed, in-air, position, battery) feeding the tracker.
  A stream that ends or raises is recorded in ``stream_errors`` and simply
  stops updating; the tracker's oldest-stream age then makes the snapshot
  stale and the authority revokes with ``TELEMETRY_LINK_LOST``.
* :func:`watch_step` / :func:`run_delegation_watch` run the periodic R6 tick:
  observe the vehicle (may revoke and queue an alert), move alerts into the
  outbox, then make at most one delivery attempt with a timeout.
* :func:`mavsdk_status_text_sender` adapts MAVSDK
  ``server_utility.send_status_text`` to the outbox's message type.

Implementation choices (not owner requirements)
-----------------------------------------------
* **Observe before sending.** Each tick checks the vehicle first, so a slow or
  failing ground link can delay an alert but never delays a revocation.
* **One send attempt per tick, bounded by ``send_timeout_s``.** A hung
  transport cannot stall the tick loop for longer than the timeout; a timeout
  or exception counts as a failed send and the outbox's retry spacing applies.
* **Failsafe state is still not sourced here.** Which MAVLink signal provides
  ``failsafe_active`` remains open (see ``delegation.py``). Without a source,
  ``TelemetryTracker.failsafe_active`` returns ``None`` and the authority
  refuses every grant, which is the conservative outcome.
* **Grant transport is out of scope.** How the operator's grant command
  reaches the Jetson is not chosen; callers pass grants to
  ``DelegationAuthority.request_grant`` themselves.

Authority boundary
------------------
Nothing here arms, takes off, changes mode or sends a flight command. The only
outbound traffic is a STATUSTEXT line for the operator. PX4 keeps
stabilization, geofence, battery and link-loss failsafes, RTL and pilot
override. Whether a companion-originated STATUSTEXT reaches and is shown by
the operator's ground station is **not observed** in SITL yet.

Timing defaults are MODEL INPUTS / development placeholders. Unit-tested only.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from coyote.autonomy.delegation import DelegationAuthority
from coyote.autonomy.ground_alerts import GroundAlertOutbox, StatusMessage
from coyote.autonomy.telemetry import Stream, TelemetryTracker, observe_vehicle

AsyncSender = Callable[[StatusMessage], Awaitable[object]]


@dataclass(frozen=True)
class WatchConfig:
    """MODEL INPUTS / PLACEHOLDERS: not derived from SITL or flight testing.

    ``tick_interval_s`` adds to revocation latency on a silent link (the
    authority's telemetry-age limit plus up to one tick plus, at worst, one
    send timeout), so keep it well below that limit.
    """

    tick_interval_s: float = 0.2
    send_timeout_s: float = 1.0

    def validate(self) -> None:
        for name in ("tick_interval_s", "send_timeout_s"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value <= 0.0
            ):
                raise ValueError(f"{name} must be a positive finite number")


# --------------------------------------------------------------- telemetry
async def _pump(
    stream: Stream,
    source: Callable[[], Any],
    handle: Callable[[Any, float], None],
    clock: Callable[[], float],
    stream_errors: dict[Stream, str],
) -> None:
    try:
        async for value in source():
            handle(value, clock())
        stream_errors[stream] = "stream ended"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # kept for the report; the snapshot then goes stale
        stream_errors[stream] = f"{type(exc).__name__}: {exc}"


def subscribe_vehicle_telemetry(
    drone: Any,
    tracker: TelemetryTracker,
    clock: Callable[[], float],
    stream_errors: dict[Stream, str],
) -> list[asyncio.Task]:
    """Start one read-only task per MAVSDK telemetry stream. Caller cancels them.

    ``drone`` needs ``telemetry.flight_mode/armed/in_air/position/battery``
    async-generator methods (a MAVSDK 3.x ``System``). ``clock`` must be
    monotonic and the same clock the watch loop uses. A missing attribute on a
    received value is passed on as ``None`` so the tracker treats it as
    malformed (position) or unknown (battery) instead of crashing the task.
    """

    t = tracker
    telemetry = drone.telemetry
    specs = (
        (Stream.FLIGHT_MODE, telemetry.flight_mode, t.update_flight_mode),
        (Stream.ARMED, telemetry.armed, t.update_armed),
        (Stream.IN_AIR, telemetry.in_air, t.update_in_air),
        (
            Stream.POSITION,
            telemetry.position,
            lambda p, now: t.update_position(getattr(p, "relative_altitude_m", None), now),
        ),
        (
            Stream.BATTERY,
            telemetry.battery,
            lambda b, now: t.update_battery_percent(getattr(b, "remaining_percent", None), now),
        ),
    )
    return [
        asyncio.create_task(_pump(stream, source, handle, clock, stream_errors))
        for stream, source, handle in specs
    ]


# ------------------------------------------------------------- R6 watch tick
@dataclass(frozen=True)
class WatchTick:
    """What one tick observed and did (for logging and tests)."""

    delegated: bool
    sent: StatusMessage | None
    send_failed: bool
    pending_alerts: int


async def watch_step(
    tracker: TelemetryTracker,
    authority: DelegationAuthority,
    outbox: GroundAlertOutbox,
    send: AsyncSender,
    clock: Callable[[], float],
    config: WatchConfig | None = None,
) -> WatchTick:
    """Run one R6 tick: observe, collect alerts, try to deliver one line.

    ``send`` must return ``True`` once the transport accepted the line. Any
    other return value, an exception or exceeding ``send_timeout_s`` is a
    failed send; the alert stays queued and the outbox's retry spacing applies.
    Delivering an alert never restores delegation.
    """

    cfg = config or WatchConfig()
    cfg.validate()
    now = clock()
    observe_vehicle(tracker, authority, now)
    outbox.collect(authority)
    delegated = authority.delegated(now)

    message = outbox.next_message(now)
    sent: StatusMessage | None = None
    failed = False
    if message is not None:
        try:
            ok = await asyncio.wait_for(send(message), timeout=cfg.send_timeout_s) is True
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - timeout or any transport error is a failed send
            ok = False
        if ok:
            outbox.mark_sent()
            sent = message
        else:
            outbox.mark_failed(clock())
            failed = True
    return WatchTick(delegated, sent, failed, len(outbox.pending()))


async def run_delegation_watch(
    tracker: TelemetryTracker,
    authority: DelegationAuthority,
    outbox: GroundAlertOutbox,
    send: AsyncSender,
    clock: Callable[[], float],
    config: WatchConfig | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    on_tick: Callable[[WatchTick], None] | None = None,
) -> None:
    """Run :func:`watch_step` every ``tick_interval_s`` until cancelled."""

    cfg = config or WatchConfig()
    cfg.validate()
    while True:
        tick = await watch_step(tracker, authority, outbox, send, clock, cfg)
        if on_tick is not None:
            on_tick(tick)
        await sleep(cfg.tick_interval_s)


# ---------------------------------------------------------- alert transport
def mavsdk_status_text_sender(drone: Any, status_text_type: Any = None) -> AsyncSender:
    """Return an async sender using MAVSDK ``server_utility.send_status_text``.

    Severity is mapped by name onto ``mavsdk.server_utility.StatusTextType``
    (names checked against MAVSDK-Python 3.17.2 without a vehicle). Pass
    ``status_text_type`` to avoid importing MAVSDK, e.g. in tests. MAVSDK
    raises ``ServerUtilityError`` on failure, which :func:`watch_step` counts
    as a failed send.
    """

    if status_text_type is None:
        from mavsdk.server_utility import StatusTextType as status_text_type

    async def send(message: StatusMessage) -> bool:
        severity = getattr(status_text_type, message.severity.name)
        await drone.server_utility.send_status_text(severity, message.text)
        return True

    return send
