"""PX4 SITL waypoint mission upload and read-back check (X500 flight layer).

Simulation only. Connects to the loopback SITL endpoint (the same guard as the
smoke mission), waits for position/home health, reads PX4 home, refuses unless
the preflight gate shows a disarmed vehicle on the ground (so an active mission
is never replaced), checks the waypoint file against the X500 advisory limits
(model inputs), uploads the mission, downloads it back and compares every item.

It never arms, starts the mission or sends a flight command. PASS means PX4
accepted the mission and returned the same items within the read-back
tolerances; it says nothing about flying the mission.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from shared.autonomy.sitl import SitlMissionConfig, load_sitl_config
from simulation.mavsdk.smoke_mission import _wait_for_connection, _wait_for_health
from x500.flight.preflight import require_preflight_ready
from x500.flight.settings import X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS
from x500.flight.waypoint_mission import (
    HomePosition,
    LocalWaypoint,
    MultirotorMissionLimits,
    build_mission_items,
    upload_and_verify,
)

_WAYPOINT_KEYS = {"north_m", "east_m", "relative_altitude_m", "speed_m_s", "is_fly_through"}


def load_waypoints(path: str | Path) -> list[LocalWaypoint]:
    """Read ``{"waypoints": [...]}``; unknown or missing keys are errors."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"waypoints"}:
        raise ValueError('Waypoint file must be an object with only a "waypoints" list')
    raw = payload["waypoints"]
    if not isinstance(raw, list):
        raise ValueError('"waypoints" must be a list')
    waypoints = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict) or set(entry) != _WAYPOINT_KEYS:
            raise ValueError(
                f"Waypoint {index} must have exactly the keys {sorted(_WAYPOINT_KEYS)}"
            )
        if not isinstance(entry["is_fly_through"], bool):
            raise ValueError(f"Waypoint {index} is_fly_through must be true or false")
        waypoints.append(
            LocalWaypoint(
                north_m=float(entry["north_m"]),
                east_m=float(entry["east_m"]),
                relative_altitude_m=float(entry["relative_altitude_m"]),
                speed_m_s=float(entry["speed_m_s"]),
                is_fly_through=entry["is_fly_through"],
            )
        )
    return waypoints


async def _read_home(drone, timeout_s: float) -> HomePosition:
    async def wait() -> HomePosition:
        async for home in drone.telemetry.home():
            return HomePosition(home.latitude_deg, home.longitude_deg)
        raise RuntimeError("Home telemetry stream ended before a home position")

    home = await asyncio.wait_for(wait(), timeout=timeout_s)
    home.validate()
    return home


async def run_upload_check(
    config: SitlMissionConfig,
    waypoints: list[LocalWaypoint],
    limits: MultirotorMissionLimits,
) -> int:
    # Import here so unit tests do not require MAVSDK to be installed.
    from mavsdk import System
    from mavsdk import mission as mavsdk_mission

    config.validate()  # refuses non-loopback, wildcard and serial endpoints
    drone = System()
    print(f"Connecting to PX4 SITL at {config.system_address} ...")
    await drone.connect(system_address=config.system_address)
    await _wait_for_connection(drone, config.connection_timeout_s)
    await _wait_for_health(drone, config.health_timeout_s)
    home = await _read_home(drone, config.health_timeout_s)
    print(f"Home {home.latitude_deg:.7f}, {home.longitude_deg:.7f}")
    await require_preflight_ready(
        drone, X500_SITL_PREFLIGHT_LIMITS, config.health_timeout_s, time.monotonic
    )

    items = build_mission_items(waypoints, home, limits)
    count = await upload_and_verify(drone, items, home, mavsdk_mission)
    print(f"PASS: {count} waypoints uploaded and read back unchanged (mission not started).")
    return count


def parse_args() -> argparse.Namespace:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description="X500 SITL waypoint upload/read-back check")
    parser.add_argument("--config", type=Path, default=here / "sitl_config.json")
    parser.add_argument("--mission", type=Path, default=here / "x500_waypoint_square.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_sitl_config(args.config)
    waypoints = load_waypoints(args.mission)
    asyncio.run(run_upload_check(config, waypoints, X500_SITL_MISSION_LIMITS))


if __name__ == "__main__":
    main()
