"""PX4 SITL waypoint mission flight with execution monitoring (X500 flight layer).

Simulation only. Refuses any vehicle endpoint other than the loopback SITL
listener (same guard as the smoke mission). Sequence:

1. Check the waypoint file against the X500 advisory limits (model inputs).
2. Connect, wait for position/home health, read PX4 home.
3. Start read-only telemetry subscriptions, upload the mission and verify it by
   read-back (``upload_and_verify``).
4. Arm (PX4 arming checks stay enabled) and request ``start_mission``.
5. Run :class:`MissionExecutionMonitor` on the combined telemetry until it ends.
6. Request ``RETURN_TO_LAUNCH`` only if :func:`follow_up_request` allows it
   (mission completed, or the monitor recommended RTL, with fresh telemetry
   still showing an armed, airborne vehicle in MISSION/HOLD), then wait for
   landing. Any other outcome sends nothing: PX4 or the pilot owns the vehicle.

PASS means the monitor saw the mission complete and the vehicle landed after
the RTL request, in simulation. **Not yet run against PX4 SITL.**
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
    _wait_until_landed,
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
from x500.flight.monitor_settings import x500_sitl_monitor_settings
from x500.flight.settings import X500_SITL_MISSION_LIMITS
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
LANDING_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class FlightResult:
    status: MissionStatus
    rtl_requested: bool
    follow_up_reason: str
    landed: bool
    stream_errors: dict

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
    landing_timeout_s: float = LANDING_TIMEOUT_S,
) -> FlightResult:
    """Fly one verified mission on an already connected *simulated* vehicle."""

    await _wait_for_health(drone, health_timeout_s)
    home = await _read_home(drone, health_timeout_s)
    items = build_mission_items(waypoints, home, limits)
    settings = settings_for(len(items))
    monitor = MissionExecutionMonitor(settings)

    combiner = MissionTelemetryCombiner()
    tasks = subscribe_mission_telemetry(drone, combiner, clock)
    try:
        await upload_and_verify(drone, items, home, mission_module)
        print(f"Mission of {len(items)} items verified; arming (PX4 checks enabled) ...")
        await drone.action.arm()
        await drone.mission.start_mission()
        started_at = clock()
        monitor.start(started_at)
        print("Mission start requested; monitoring ...")
        status = await run_monitor(monitor, combiner, started_at, clock, check_interval_s)
        print(f"Monitor: {status.state.value} {status.reason or ''} {status.detail}".rstrip())

        follow = follow_up_request(status, combiner.sample(), clock(), settings.max_telemetry_age_s)
        landed = False
        if follow.request_return_to_launch:
            print("Requesting PX4 RETURN_TO_LAUNCH ...")
            await drone.action.return_to_launch()
            await _wait_until_landed(drone, landing_timeout_s)
            landed = True
        else:
            print(f"No follow-up command: {follow.reason}")
        return FlightResult(
            status=status,
            rtl_requested=follow.request_return_to_launch,
            follow_up_reason=follow.reason,
            landed=landed,
            stream_errors={s.value: d for s, d in combiner.stream_errors.items()},
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
        raise SystemExit("FAIL: monitored SITL waypoint mission did not complete and land.")
    print("PASS: simulated waypoint mission completed, RTL requested, vehicle landed.")


if __name__ == "__main__":
    main()
