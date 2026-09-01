"""Small, dependency-free helpers for PX4 SITL development.

This module intentionally contains no MAVSDK import so it can be unit-tested in
CI without a simulator or vehicle present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SitlMissionConfig:
    system_address: str = "udp://:14540"
    takeoff_altitude_m: float = 3.0
    loiter_seconds: float = 5.0
    connection_timeout_s: float = 30.0
    health_timeout_s: float = 60.0

    def validate(self) -> None:
        if not is_local_sitl_address(self.system_address):
            raise ValueError(
                "Smoke mission is simulation-only. Refusing non-local vehicle address: "
                f"{self.system_address!r}"
            )
        if not 1.0 <= self.takeoff_altitude_m <= 10.0:
            raise ValueError("SITL takeoff altitude must be between 1 and 10 meters")
        if not 0.0 <= self.loiter_seconds <= 60.0:
            raise ValueError("SITL loiter time must be between 0 and 60 seconds")
        if self.connection_timeout_s <= 0 or self.health_timeout_s <= 0:
            raise ValueError("Timeouts must be positive")


def is_local_sitl_address(address: str) -> bool:
    """Return True only for the local UDP endpoint reserved for our SITL smoke test."""
    normalized = address.strip().lower()
    return normalized in {
        "udp://:14540",
        "udp://0.0.0.0:14540",
        "udp://127.0.0.1:14540",
        "udp://localhost:14540",
    }


def load_sitl_config(path: str | Path) -> SitlMissionConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    config = SitlMissionConfig(**payload)
    config.validate()
    return config
