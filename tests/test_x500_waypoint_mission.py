import asyncio
import json
import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

from simulation.mavsdk.waypoint_upload_check import load_waypoints
from x500.flight.settings import X500_SITL_MISSION_LIMITS
from x500.flight.waypoint_mission import (
    HomePosition,
    LocalWaypoint,
    MissionCheckError,
    MissionReadbackError,
    MultirotorMissionLimits,
    build_mission_items,
    check_mission,
    compare_readback,
    global_to_local,
    local_to_global,
    to_mavsdk_plan,
    upload_and_verify,
)

HOME = HomePosition(41.6262, -71.2531)  # arbitrary test origin, not a survey site
LIMITS = MultirotorMissionLimits(
    max_relative_altitude_m=30.0,
    min_waypoint_altitude_m=3.0,
    max_distance_from_home_m=100.0,
    max_speed_m_s=5.0,
    max_waypoints=5,
)
SQUARE = [
    LocalWaypoint(0.0, 0.0, 10.0, 3.0, False),
    LocalWaypoint(20.0, 0.0, 10.0, 3.0),
    LocalWaypoint(20.0, 20.0, 10.0, 3.0),
    LocalWaypoint(0.0, 0.0, 10.0, 3.0, False),
]


# --- fake mavsdk.mission module ------------------------------------------------


class _FakeMissionItem:
    class CameraAction:
        NONE = "camera-none"

    class VehicleAction:
        NONE = "vehicle-none"

    def __init__(self, **fields):
        self.__dict__.update(fields)


class _FakeMissionPlan:
    def __init__(self, mission_items):
        self.mission_items = mission_items


FAKE_MISSION_MODULE = SimpleNamespace(MissionItem=_FakeMissionItem, MissionPlan=_FakeMissionPlan)


class _FakeMissionPlugin:
    """Stores the uploaded plan; ``alter`` lets a test model a vehicle-side change."""

    def __init__(self, alter=None):
        self.uploaded = None
        self.alter = alter

    async def upload_mission(self, plan):
        self.uploaded = plan

    async def download_mission(self):
        items = list(self.uploaded.mission_items)
        if self.alter:
            items = self.alter(items)
        return _FakeMissionPlan(items)


# --- limits and checks ---------------------------------------------------------


def test_x500_sitl_limits_are_valid_model_inputs() -> None:
    X500_SITL_MISSION_LIMITS.validate()


def test_valid_square_passes_checks() -> None:
    assert check_mission(SQUARE, LIMITS) == []


def test_empty_mission_is_refused() -> None:
    assert check_mission([], LIMITS) == ["mission has no waypoints"]


@pytest.mark.parametrize(
    ("waypoint", "fragment"),
    [
        (LocalWaypoint(90.0, 50.0, 10.0, 3.0), "from home"),
        (LocalWaypoint(0.0, 0.0, 31.0, 3.0), "exceeds"),
        (LocalWaypoint(0.0, 0.0, 2.0, 3.0), "below"),
        (LocalWaypoint(0.0, 0.0, 10.0, 6.0), "speed"),
        (LocalWaypoint(0.0, 0.0, 10.0, 0.0), "speed"),
        (LocalWaypoint(math.nan, 0.0, 10.0, 3.0), "non-finite"),
    ],
)
def test_out_of_limit_waypoint_is_refused_not_clipped(waypoint, fragment) -> None:
    reasons = check_mission([SQUARE[0], waypoint], LIMITS)
    assert len(reasons) == 1 and fragment in reasons[0] and "waypoint 1" in reasons[0]
    with pytest.raises(MissionCheckError):
        build_mission_items([SQUARE[0], waypoint], HOME, LIMITS)


def test_too_many_waypoints_is_refused() -> None:
    reasons = check_mission([SQUARE[0]] * 6, LIMITS)
    assert reasons == ["mission has 6 waypoints; limit is 5"]


def test_all_problems_are_reported_together() -> None:
    reasons = check_mission(
        [LocalWaypoint(200.0, 0.0, 50.0, 3.0), LocalWaypoint(0.0, 0.0, 10.0, 9.0)], LIMITS
    )
    assert len(reasons) == 3


@pytest.mark.parametrize(
    "bad",
    [
        replace(LIMITS, min_waypoint_altitude_m=40.0),
        replace(LIMITS, max_relative_altitude_m=150.0, min_waypoint_altitude_m=3.0),
        replace(LIMITS, max_distance_from_home_m=5_000.0),
        replace(LIMITS, max_speed_m_s=math.inf),
        replace(LIMITS, max_waypoints=0),
    ],
)
def test_invalid_limits_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        check_mission(SQUARE, bad)


# --- projection ---------------------------------------------------------------


def test_projection_round_trip_within_a_millimetre() -> None:
    for north, east in [(0.0, 0.0), (100.0, -40.0), (-1_500.0, 1_200.0)]:
        lat, lon = local_to_global(HOME, north, east)
        back = global_to_local(HOME, lat, lon)
        assert back == pytest.approx((north, east), abs=1e-3)


def test_projection_scale_is_metres() -> None:
    lat, _ = local_to_global(HOME, 111.19, 0.0)
    assert lat - HOME.latitude_deg == pytest.approx(0.001, rel=1e-3)


def test_bad_home_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_mission_items(SQUARE, HomePosition(85.0, 0.0), LIMITS)


# --- read-back comparison -------------------------------------------------------


def _items():
    return build_mission_items(SQUARE, HOME, LIMITS)


def _as_downloaded(items):
    return list(to_mavsdk_plan(items, FAKE_MISSION_MODULE).mission_items)


def test_identical_readback_has_no_mismatch() -> None:
    items = _items()
    assert compare_readback(items, _as_downloaded(items), HOME) == []


def test_mavlink_integer_rounding_is_tolerated() -> None:
    items = _items()
    rounded = [
        replace(
            item,
            latitude_deg=round(item.latitude_deg * 1e7) / 1e7,
            longitude_deg=round(item.longitude_deg * 1e7) / 1e7,
        )
        for item in items
    ]
    assert compare_readback(items, rounded, HOME) == []


def test_missing_item_is_detected() -> None:
    items = _items()
    mismatches = compare_readback(items, _as_downloaded(items)[:-1], HOME)
    assert mismatches == ["downloaded 3 items; uploaded 4"]


def test_extra_item_is_detected() -> None:
    items = _items()
    downloaded = _as_downloaded(items) + _as_downloaded(items)[:1]
    assert compare_readback(items, downloaded, HOME) == ["downloaded 5 items; uploaded 4"]


def test_reordered_items_are_detected() -> None:
    items = _items()
    downloaded = _as_downloaded(items)
    downloaded[1], downloaded[2] = downloaded[2], downloaded[1]
    mismatches = compare_readback(items, downloaded, HOME)
    assert any("item 1 position" in m for m in mismatches)
    assert any("item 2 position" in m for m in mismatches)


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("relative_altitude_m", 10.5, "altitude"),
        ("speed_m_s", 5.0, "speed"),
        ("is_fly_through", True, "fly-through"),
        ("speed_m_s", math.nan, "non-finite"),
    ],
)
def test_changed_field_is_detected(field, value, fragment) -> None:
    items = _items()
    downloaded = _as_downloaded(items)
    setattr(downloaded[0], field, value)
    mismatches = compare_readback(items, downloaded, HOME)
    assert len(mismatches) == 1 and mismatches[0].startswith("item 0") and fragment in mismatches[0]


def test_position_shift_beyond_tolerance_is_detected() -> None:
    items = _items()
    shifted = list(items)
    lat, lon = local_to_global(HOME, 20.5, 0.0)
    shifted[1] = replace(items[1], latitude_deg=lat, longitude_deg=lon)
    mismatches = compare_readback(items, shifted, HOME)
    assert mismatches == ["item 1 position differs by 0.50 m"]


def test_item_without_fields_is_a_mismatch() -> None:
    items = _items()
    downloaded = _as_downloaded(items)
    downloaded[2] = SimpleNamespace(latitude_deg=0.0)
    assert compare_readback(items, downloaded, HOME) == ["item 2 is missing a required field"]


# --- MAVSDK conversion and upload/verify ---------------------------------------


def test_mavsdk_plan_sets_only_controlled_fields() -> None:
    item = to_mavsdk_plan(_items(), FAKE_MISSION_MODULE).mission_items[1]
    assert item.vehicle_action == _FakeMissionItem.VehicleAction.NONE
    assert item.camera_action == _FakeMissionItem.CameraAction.NONE
    assert math.isnan(item.loiter_time_s) and math.isnan(item.acceptance_radius_m)
    assert item.speed_m_s == 3.0 and item.is_fly_through is True


def test_upload_and_verify_passes_on_faithful_readback() -> None:
    plugin = _FakeMissionPlugin()
    drone = SimpleNamespace(mission=plugin)
    count = asyncio.run(upload_and_verify(drone, _items(), HOME, FAKE_MISSION_MODULE))
    assert count == 4 and len(plugin.uploaded.mission_items) == 4


def test_upload_and_verify_raises_on_truncated_readback() -> None:
    drone = SimpleNamespace(mission=_FakeMissionPlugin(alter=lambda items: items[:2]))
    with pytest.raises(MissionReadbackError, match="downloaded 2 items; uploaded 4"):
        asyncio.run(upload_and_verify(drone, _items(), HOME, FAKE_MISSION_MODULE))


def test_upload_and_verify_raises_on_empty_download() -> None:
    drone = SimpleNamespace(mission=_FakeMissionPlugin(alter=lambda items: []))
    with pytest.raises(MissionReadbackError):
        asyncio.run(upload_and_verify(drone, _items(), HOME, FAKE_MISSION_MODULE))


def test_upload_and_verify_refuses_empty_mission_without_uploading() -> None:
    plugin = _FakeMissionPlugin()
    with pytest.raises(MissionCheckError):
        asyncio.run(
            upload_and_verify(SimpleNamespace(mission=plugin), (), HOME, FAKE_MISSION_MODULE)
        )
    assert plugin.uploaded is None


def test_upload_and_verify_sends_no_flight_commands() -> None:
    # The drone fake exposes only the mission upload/download API; any attempt to
    # arm, start the mission or use the action plugin would raise AttributeError.
    plugin = _FakeMissionPlugin()
    asyncio.run(
        upload_and_verify(SimpleNamespace(mission=plugin), _items(), HOME, FAKE_MISSION_MODULE)
    )


# --- waypoint file ---------------------------------------------------------------


def test_bundled_square_mission_loads_and_passes_x500_limits() -> None:
    from pathlib import Path

    path = Path("simulation/mavsdk/x500_waypoint_square.json")
    waypoints = load_waypoints(path)
    assert len(waypoints) == 5
    build_mission_items(waypoints, HOME, X500_SITL_MISSION_LIMITS)


@pytest.mark.parametrize(
    "payload",
    [
        {"waypoints": [{"north_m": 0, "east_m": 0, "relative_altitude_m": 5, "speed_m_s": 2}]},
        {"waypoints": [], "extra": 1},
        {
            "waypoints": [
                {
                    "north_m": 0,
                    "east_m": 0,
                    "relative_altitude_m": 5,
                    "speed_m_s": 2,
                    "is_fly_through": "yes",
                }
            ]
        },
        {"waypoints": {}},
    ],
)
def test_malformed_waypoint_file_is_rejected(tmp_path, payload) -> None:
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_waypoints(path)
