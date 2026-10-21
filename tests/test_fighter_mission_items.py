import dataclasses
import math

import pytest

from fighter_vtol.mission.mission_items import (
    EARTH_RADIUS_M,
    HomePosition,
    MissionExportError,
    VehicleAction,
    build_mission_items,
    check_plan_structure,
    global_to_local,
    local_to_global,
)
from fighter_vtol.mission.survey_plan import Phase, PlanItem, SurveyArea, plan_survey

# Illustrative coordinates only (roughly Narragansett Bay latitude); not a
# surveyed home point, launch site or approved operating area.
HOME = HomePosition(latitude_deg=41.60, longitude_deg=-71.25)


def _plan():
    area = SurveyArea(
        start_north_m=400.0,
        start_east_m=-200.0,
        line_heading_deg=90.0,
        line_length_m=400.0,
        cross_track_width_m=300.0,
        line_spacing_m=60.0,
    )
    return plan_survey(area)


def test_projection_of_home_is_home() -> None:
    assert local_to_global(HOME, 0.0, 0.0) == (HOME.latitude_deg, HOME.longitude_deg)
    assert global_to_local(HOME, HOME.latitude_deg, HOME.longitude_deg) == (0.0, 0.0)


def test_projection_matches_spherical_scale() -> None:
    lat, lon = local_to_global(HOME, 1000.0, 0.0)
    assert lat - HOME.latitude_deg == pytest.approx(math.degrees(1000.0 / EARTH_RADIUS_M), rel=1e-9)
    assert lon == pytest.approx(HOME.longitude_deg, abs=1e-12)

    lat, lon = local_to_global(HOME, 0.0, 1000.0)
    expected = math.degrees(1000.0 / (EARTH_RADIUS_M * math.cos(math.radians(HOME.latitude_deg))))
    assert lon - HOME.longitude_deg == pytest.approx(expected, rel=1e-4)
    # East displacement must not move the point north.
    assert lat == pytest.approx(HOME.latitude_deg, abs=1e-6)


@pytest.mark.parametrize(
    "north, east", [(1500.0, -900.0), (-250.0, 30.0), (0.0, -1499.0), (7000.0, 7000.0)]
)
def test_projection_round_trip_is_millimetre_exact(north: float, east: float) -> None:
    lat, lon = local_to_global(HOME, north, east)
    back = global_to_local(HOME, lat, lon)
    assert back == pytest.approx((north, east), abs=1e-3)


def test_projection_preserves_great_circle_distance_from_home() -> None:
    # Azimuthal-equidistant property, checked with an independent haversine.
    lat0, lon0 = math.radians(HOME.latitude_deg), math.radians(HOME.longitude_deg)
    for north, east in ((1200.0, 800.0), (-3000.0, 4000.0)):
        lat, lon = (math.radians(v) for v in local_to_global(HOME, north, east))
        h = (
            math.sin((lat - lat0) / 2) ** 2
            + math.cos(lat0) * math.cos(lat) * math.sin((lon - lon0) / 2) ** 2
        )
        distance = 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))
        assert distance == pytest.approx(math.hypot(north, east), abs=1e-3)


def test_projection_wraps_across_antimeridian() -> None:
    home = HomePosition(latitude_deg=0.0, longitude_deg=179.999)
    _, lon = local_to_global(home, 0.0, 1000.0)
    assert -180.0 <= lon < -179.99
    north, east = global_to_local(home, 0.0, lon)
    assert (north, east) == pytest.approx((0.0, 1000.0), abs=1e-3)


@pytest.mark.parametrize(
    "home",
    [
        HomePosition(math.nan, 0.0),
        HomePosition(0.0, math.inf),
        HomePosition(85.0, 0.0),
        HomePosition(0.0, 181.0),
    ],
)
def test_invalid_home_is_rejected(home: HomePosition) -> None:
    with pytest.raises(ValueError):
        local_to_global(home, 10.0, 10.0)
    with pytest.raises(ValueError):
        build_mission_items(_plan(), home)


def test_far_or_non_finite_local_points_are_rejected() -> None:
    with pytest.raises(ValueError, match="projection limit"):
        local_to_global(HOME, 10_001.0, 0.0)
    with pytest.raises(ValueError, match="finite"):
        local_to_global(HOME, math.nan, 0.0)


def test_planner_output_converts_with_expected_actions() -> None:
    plan = _plan()
    specs = build_mission_items(plan, HOME)

    assert len(specs) == len(plan.items)
    assert [s.vehicle_action for s in specs[:2]] == [
        VehicleAction.TAKEOFF,
        VehicleAction.TRANSITION_TO_FW,
    ]
    assert [s.vehicle_action for s in specs[-2:]] == [
        VehicleAction.TRANSITION_TO_MC,
        VehicleAction.LAND,
    ]
    assert {s.vehicle_action for s in specs[2:-2]} == {VehicleAction.NONE}
    # Only plain waypoints are fly-through; action items are stopping points.
    for spec in specs:
        assert spec.is_fly_through is (spec.vehicle_action is VehicleAction.NONE)


def test_conversion_preserves_geometry_altitude_and_line_tags() -> None:
    plan = _plan()
    specs = build_mission_items(plan, HOME)
    for item, spec in zip(plan.items, specs, strict=True):
        assert spec.relative_altitude_m == item.altitude_m
        assert spec.role == item.role
        assert spec.line_index == item.line_index
        north, east = global_to_local(HOME, spec.latitude_deg, spec.longitude_deg)
        assert (north, east) == pytest.approx((item.north_m, item.east_m), abs=1e-3)
    # Takeoff and landing are exactly at home.
    for spec in (specs[0], specs[-1]):
        assert (spec.latitude_deg, spec.longitude_deg) == (HOME.latitude_deg, HOME.longitude_deg)


def test_conversion_is_deterministic() -> None:
    assert build_mission_items(_plan(), HOME) == build_mission_items(_plan(), HOME)


def _replace(plan, items):
    return dataclasses.replace(plan, items=tuple(items))


def test_planner_output_has_valid_structure() -> None:
    assert check_plan_structure(_plan().items) == []


def test_waypoint_before_forward_transition_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    items[1], items[2] = items[2], items[1]
    with pytest.raises(MissionExportError, match="forward transition"):
        build_mission_items(_replace(plan, items), HOME)


def test_landing_without_back_transition_is_refused() -> None:
    plan = _plan()
    items = [i for i in plan.items if i.phase is not Phase.TRANSITION_TO_MC]
    with pytest.raises(MissionExportError, match="back transition"):
        build_mission_items(_replace(plan, items), HOME)


def test_truncated_plan_is_refused() -> None:
    plan = _plan()
    with pytest.raises(MissionExportError, match="VTOL landing"):
        build_mission_items(_replace(plan, plan.items[:-1]), HOME)
    with pytest.raises(MissionExportError, match="at least 5"):
        build_mission_items(_replace(plan, plan.items[:3]), HOME)


def test_action_inside_fixed_wing_legs_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    middle = items[5]
    items[5] = dataclasses.replace(middle, phase=Phase.VTOL_LAND)
    with pytest.raises(MissionExportError, match="only fixed-wing waypoints"):
        build_mission_items(_replace(plan, items), HOME)


def test_landing_away_from_home_or_above_ground_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    items[-1] = dataclasses.replace(items[-1], north_m=50.0)
    with pytest.raises(MissionExportError, match="at home"):
        build_mission_items(_replace(plan, items), HOME)

    items = list(plan.items)
    items[-1] = dataclasses.replace(items[-1], altitude_m=5.0)
    with pytest.raises(MissionExportError, match="landing altitude"):
        build_mission_items(_replace(plan, items), HOME)


def test_waypoint_at_or_below_home_altitude_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    items[4] = dataclasses.replace(items[4], altitude_m=0.0)
    with pytest.raises(MissionExportError, match="above home"):
        build_mission_items(_replace(plan, items), HOME)


def test_hand_edited_altitude_above_ceiling_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    items[4] = dataclasses.replace(items[4], altitude_m=200.0)
    with pytest.raises(MissionExportError, match="exceeds 120 m"):
        build_mission_items(_replace(plan, items), HOME)
    # Exactly at the ceiling is allowed.
    items[4] = dataclasses.replace(items[4], altitude_m=120.0)
    assert build_mission_items(_replace(plan, items), HOME)


def test_non_finite_item_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    items[3] = dataclasses.replace(items[3], east_m=math.nan)
    with pytest.raises(MissionExportError, match="non-finite"):
        build_mission_items(_replace(plan, items), HOME)


def test_hand_built_item_beyond_projection_limit_is_refused() -> None:
    plan = _plan()
    items = list(plan.items)
    far = PlanItem(Phase.FW_WAYPOINT, 20_000.0, 0.0, 80.0, "line_entry", 0)
    items.insert(3, far)
    with pytest.raises(MissionExportError, match="projection limit"):
        build_mission_items(_replace(plan, items), HOME)
