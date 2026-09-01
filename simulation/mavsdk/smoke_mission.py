"""PX4 SITL + MAVSDK smoke mission.

Purpose: prove the software path from Python -> MAVSDK -> PX4 SITL before any
real-aircraft autonomy work. The script deliberately refuses non-local vehicle
addresses.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from shared.autonomy.sitl import SitlMissionConfig, load_sitl_config


async def _wait_for_connection(drone, timeout_s: float) -> None:
    async def wait() -> None:
        async for state in drone.core.connection_state():
            if state.is_connected:
                return

    await asyncio.wait_for(wait(), timeout=timeout_s)


async def _wait_for_health(drone, timeout_s: float) -> None:
    async def wait() -> None:
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                return

    await asyncio.wait_for(wait(), timeout=timeout_s)


async def _wait_until_landed(drone, timeout_s: float = 30.0) -> None:
    async def wait() -> None:
        async for in_air in drone.telemetry.in_air():
            if not in_air:
                return

    await asyncio.wait_for(wait(), timeout=timeout_s)


async def run_smoke_mission(config: SitlMissionConfig) -> None:
    # Import here so configuration/unit tests do not require MAVSDK to be installed.
    from mavsdk import System

    config.validate()
    drone = System()

    print(f"Connecting to PX4 SITL at {config.system_address} ...")
    await drone.connect(system_address=config.system_address)
    await _wait_for_connection(drone, config.connection_timeout_s)
    print("Connected.")

    print("Waiting for simulated position/home health ...")
    await _wait_for_health(drone, config.health_timeout_s)
    print("Health checks passed.")

    await drone.action.set_takeoff_altitude(config.takeoff_altitude_m)
    print(f"Arming and taking off to {config.takeoff_altitude_m:.1f} m ...")
    await drone.action.arm()
    await drone.action.takeoff()

    await asyncio.sleep(config.loiter_seconds)

    print("Landing ...")
    await drone.action.land()
    await _wait_until_landed(drone)
    print("PASS: simulated arm -> takeoff -> loiter -> land mission completed.")


def parse_args() -> argparse.Namespace:
    default_config = Path(__file__).with_name("sitl_config.json")
    parser = argparse.ArgumentParser(
        description="Run the Wildlife Drone Program SITL smoke mission"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help=f"Path to SITL JSON configuration (default: {default_config})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_sitl_config(args.config)
    asyncio.run(run_smoke_mission(config))


if __name__ == "__main__":
    main()
