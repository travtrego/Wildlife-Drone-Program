"""PX4 SITL waypoint mission flight with execution monitoring (X500 flight layer).

Simulation only. Refuses any vehicle endpoint other than the loopback SITL
listener (same guard as the smoke mission). Sequence:

1. Check the waypoint file against the X500 advisory limits (model inputs).
2. Connect, wait for position/home health, read PX4 home.
3. Preflight gate (``require_preflight_ready``): refuse, sending nothing, unless
   fresh telemetry shows a disarmed vehicle on the ground, battery at or above
   the companion minimum and every PX4 health flag, including ``is_armable``,
   True. This keeps the script from replacing a mission on a vehicle that is
   already armed or flying.
3a. PX4 limit check (``require_px4_limits_consistent``): read ``GF_MAX_HOR_DIST``,
   ``GF_MAX_VER_DIST``, ``GF_ACTION``, ``MPC_XY_VEL_MAX``, ``BAT_LOW_THR`` and
   ``RTL_RETURN_ALT`` (read-only) and refuse, sending nothing, if the companion
   limits are looser than PX4's, a PX4 geofence limit is disabled (0),
   ``GF_ACTION`` is not Hold/Return/Land, PX4's RTL altitude is above its
   vertical geofence, or a value cannot be read.
4. Start read-only telemetry subscriptions, upload the mission and verify it by
   read-back (``upload_and_verify``).
5. Re-run the preflight gate, then arm (PX4 arming checks stay enabled) and
   request ``start_mission``.
6. Run :class:`MissionExecutionMonitor` on the combined telemetry until it ends.
   A read-only :class:`MissionTrace` prints every mode/armed/in-air/progress
   and monitor change as it happens and a summary (stream rates, item times,
   margins against the timing placeholders) when the script exits.
7. Request ``RETURN_TO_LAUNCH`` only if :func:`follow_up_request` allows it
   (mission completed, or the monitor recommended RTL, with fresh telemetry
   still showing an armed, airborne vehicle in MISSION/HOLD). Any other outcome
   sends nothing: PX4 or the pilot owns the vehicle.
8. After an RTL request, :class:`ReturnLandingMonitor` watches the same
   telemetry (read-only) until PX4 reports RTL/LAND, lands and disarms, or the
   watch ends (request not accepted, pilot takeover, PX4 left RTL/LAND, landed
   but not disarmed, timeout, stale telemetry). It sends nothing further in
   any case: no retry, no LAND, no disarm.

PASS means the monitor saw the mission complete and, after the RTL request,
the return watch saw PX4 enter RTL/LAND, land and disarm, in simulation. One
nominal PX4 SITL pass (before the return watch existed) is recorded in
docs/SITL_VALIDATION_2026-11-01.md; failure paths and the return watch are
unit-tested only.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.autonomy.sitl import SitlMissionConfig, load_sitl_config
from simulation.mavsdk.smoke_mission import (
    _wait_for_connection,
    _wait_for_health,
)
from simulation.mavsdk.waypoint_upload_check import _read_home, load_waypoints
from x500.flight.mission_monitor import (
    MissionExecutionMonitor,
    MissionState,
    MissionStatus,
    MonitorSettings,
)
from x500.flight.mission_telemetry import (
    MissionTelemetryCombiner,
    follow_up_request,
    run_monitor,
    subscribe_mission_telemetry,
)
from x500.flight.mission_trace import MissionTrace
from x500.flight.monitor_settings import (
    X500_SITL_RETURN_SETTINGS,
    x500_sitl_monitor_settings,
)
from x500.flight.preflight import PreflightLimits, require_preflight_ready
from x500.flight.px4_limits import require_px4_limits_consistent
from x500.flight.return_monitor import ReturnLandingMonitor, ReturnSettings, ReturnStatus
from x500.flight.settings import X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS
from x500.flight.waypoint_mission import (
    LocalWaypoint,
    MissionCheckError,
    MultirotorMissionLimits,
    build_mission_items,
    check_mission,
    upload_and_verify,
)

# Placeholders for SITL development, not measured values.
CHECK_INTERVAL_S = 0.2


@dataclass(frozen=True)
class FlightResult:
    status: MissionStatus
    rtl_requested: bool
    follow_up_reason: str
    landed: bool
    stream_errors: dict
    trace_lines: tuple[str, ...] = ()
    # Return watch result after an RTL request; None when no RTL was requested.
    return_status: ReturnStatus | None = None

    @property
    def passed(self) -> bool:
        return self.status.state is MissionState.COMPLETED and self.rtl_requested and self.landed


async def fly_waypoint_mission(
    drone: Any,
    waypoints: list[LocalWaypoint],
    limits: MultirotorMissionLimits,
    mission_module: Any,
    health_timeout_s: float,
    settings_for: Callable[[int], MonitorSettings] = x500_sitl_monitor_settings,
    clock: Callable[[], float] = time.monotonic,
    check_interval_s: float = CHECK_INTERVAL_S,
    return_settings: ReturnSettings = X500_SITL_RETURN_SETTINGS,
    preflight_limits: PreflightLimits = X500_SITL_PREFLIGHT_LIMITS,
    emit: Callable[[str], None] | None = print,
) -> FlightResult:
    """Fly one verified mission on an already connected *simulated* vehicle.

    Raises :class:`PreflightRefused` before upload, or before arm, if the
    vehicle is not ready, and :class:`Px4LimitsRefused` before upload if the
    companion limits contradict the PX4 parameters; nothing is sent in either case.
    """

    await _wait_for_health(drone, health_timeout_s)
    home = await _read_home(drone, health_timeout_s)
    await require_preflight_ready(drone, preflight_limits, health_timeout_s, clock)
    await require_px4_limits_consistent(drone, limits, preflight_limits, health_timeout_s)
    items = build_mission_items(waypoints, home, limits)
    settings = settings_for(len(items))
    monitor = MissionExecutionMonitor(settings)

    # Read-only trace: prints each mode/armed/in-air/progress/monitor change and
    # summarizes stream rates, item times and placeholder margins at the end.
    trace = MissionTrace(emit=emit)
    combiner = MissionTelemetryCombiner(observer=trace.observe)
    tasks = subscribe_mission_telemetry(drone, combiner, clock)
    trace_lines: tuple[str, ...] = ()
    try:
        await upload_and_verify(drone, items, home, mission_module)
        # Upload/read-back takes time; check again immediately before arming.
        await require_preflight_ready(drone, preflight_limits, health_timeout_s, clock)
        print(f"Mission of {len(items)} items verified; arming (PX4 checks enabled) ...")
        await drone.action.arm()
        await drone.mission.start_mission()
        started_at = clock()
        monitor.start(started_at)
        trace.mark_start(started_at)
        print("Mission start requested; monitoring ...")
        status = await run_monitor(
            monitor, combiner, started_at, clock, check_interval_s, on_status=trace.monitor_status
        )
        reason = status.reason.value if status.reason else ""
        print(
            f"Monitor: {status.state.value} {reason} {status.detail} "
            f"(item {status.current_item}/{status.total_items})"
        )

        follow = follow_up_request(status, combiner.sample(), clock(), settings.max_telemetry_age_s)
        landed = False
        return_status: ReturnStatus | None = None
        if follow.request_return_to_launch:
            print("Requesting PX4 RETURN_TO_LAUNCH ...")
            await drone.action.return_to_launch()
            requested_at = clock()
            watch = ReturnLandingMonitor(return_settings)
            watch.start(requested_at)
            return_status = await run_monitor(
                watch,
                combiner,
                requested_at,
                clock,
                check_interval_s,
                on_status=trace.monitor_status,
            )
            landed = return_status.landed_and_disarmed
            reason = return_status.reason.value if return_status.reason else ""
            # Read-only result; nothing further is sent whatever it says.
            print(f"Return watch: {return_status.state.value} {reason} {return_status.detail}")
        else:
            print(f"No follow-up command: {follow.reason}")
        trace_lines = tuple(trace.summary_lines(settings))
        return FlightResult(
            status=status,
            rtl_requested=follow.request_return_to_launch,
            follow_up_reason=follow.reason,
            landed=landed,
            return_status=return_status,
            stream_errors={s.value: d for s, d in combiner.stream_errors.items()},
            trace_lines=trace_lines,
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if emit is not None:
            # Printed on every exit, including refusals and exceptions after
            # subscription, so a failed run still shows what was received.
            for line in trace_lines or trace.summary_lines(settings):
                emit(line)
            if combiner.observer_error:
                emit(f"Trace stopped early: {combiner.observer_error}")


async def run_flight(
    config: SitlMissionConfig,
    waypoints: list[LocalWaypoint],
    limits: MultirotorMissionLimits,
) -> FlightResult:
    config.validate()  # refuses non-loopback, wildcard and serial endpoints
    reasons = check_mission(waypoints, limits)
    if reasons:
        raise MissionCheckError(reasons)
    # Import here so unit tests do not require MAVSDK to be installed.
    from mavsdk import System
    from mavsdk import mission as mavsdk_mission

    drone = System()
    print(f"Connecting to PX4 SITL at {config.system_address} ...")
    await drone.connect(system_address=config.system_address)
    await _wait_for_connection(drone, config.connection_timeout_s)
    return await fly_waypoint_mission(
        drone, waypoints, limits, mavsdk_mission, config.health_timeout_s
    )


def parse_args() -> argparse.Namespace:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description="X500 SITL monitored waypoint mission")
    parser.add_argument("--config", type=Path, default=here / "sitl_config.json")
    parser.add_argument("--mission", type=Path, default=here / "x500_waypoint_square.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_sitl_config(args.config)
    waypoints = load_waypoints(args.mission)
    result = asyncio.run(run_flight(config, waypoints, X500_SITL_MISSION_LIMITS))
    if result.stream_errors:
        print(f"Telemetry stream problems: {result.stream_errors}")
    if not result.passed:
        raise SystemExit(
            "FAIL: monitored SITL waypoint mission did not complete, return, land and disarm."
        )
    print("PASS: simulated waypoint mission completed, RTL requested, landed and disarmed.")


if __name__ == "__main__":
    main()
