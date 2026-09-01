import json

import pytest

from shared.autonomy.sitl import SitlMissionConfig, is_local_sitl_address, load_sitl_config


def test_default_config_is_valid() -> None:
    config = SitlMissionConfig()
    config.validate()


def test_local_sitl_addresses_are_allowed() -> None:
    assert is_local_sitl_address("udp://:14540")
    assert is_local_sitl_address("udp://127.0.0.1:14540")
    assert is_local_sitl_address("udp://localhost:14540")


def test_non_local_or_wrong_port_is_rejected() -> None:
    assert not is_local_sitl_address("udp://192.168.1.20:14540")
    assert not is_local_sitl_address("udp://:14550")


def test_config_rejects_non_local_vehicle_address() -> None:
    config = SitlMissionConfig(system_address="udp://192.168.1.20:14540")
    with pytest.raises(ValueError, match="simulation-only"):
        config.validate()


def test_config_rejects_unreasonable_takeoff_altitude() -> None:
    with pytest.raises(ValueError, match="takeoff altitude"):
        SitlMissionConfig(takeoff_altitude_m=25.0).validate()


def test_load_sitl_config(tmp_path) -> None:
    path = tmp_path / "sitl.json"
    path.write_text(
        json.dumps(
            {
                "system_address": "udp://:14540",
                "takeoff_altitude_m": 2.5,
                "loiter_seconds": 3.0,
                "connection_timeout_s": 20.0,
                "health_timeout_s": 45.0,
            }
        ),
        encoding="utf-8",
    )

    config = load_sitl_config(path)
    assert config.takeoff_altitude_m == 2.5
    assert config.loiter_seconds == 3.0
