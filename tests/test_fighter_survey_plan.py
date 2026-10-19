import math

import pytest

from fighter_vtol.mission.survey_plan import (
    FighterModelInputs,
    Phase,
    SurveyArea,
    SurveyLimits,
    SurveyPlanError,
    interleaved_line_order,
    plan_survey,
)

MODEL = FighterModelInputs()
RADIUS = MODEL.min_turn_radius_m


def _area(**overrides) -> SurveyArea:
    values = dict(
        start_north_m=400.0,
        start_east_m=-200.0,
        line_heading_deg=90.0,
        line_length_m=400.0,
        cross_track_width_m=300.0,
        line_spacing_m=60.0,
    )
    values.update(overrides)
    return SurveyArea(**values)


def _survey_lines(plan):
    """Return (line_index, start_item, end_item) in flown order."""

    starts = [i for i in plan.items if i.role == "line_start"]
    ends = [i for i in plan.items if i.role == "line_end"]
    return [(s.line_index, s, e) for s, e in zip(starts, ends, strict=True)]


def test_turn_radius_matches_coordinated_turn_formula() -> None:
    # 18 m/s at 30 degrees bank: 18^2 / (9.80665 * tan 30) ~= 57.2 m.
    assert RADIUS == pytest.approx(57.22, abs=0.01)
    steeper = FighterModelInputs(planning_bank_deg=45.0)
    assert steeper.min_turn_radius_m < RADIUS


def test_phase_sequence_is_takeoff_transition_survey_transition_land() -> None:
    plan = plan_survey(_area())
    phases = [item.phase for item in plan.items]
    assert phases[:2] == [Phase.VTOL_TAKEOFF, Phase.TRANSITION_TO_FW]
    assert phases[-2:] == [Phase.TRANSITION_TO_MC, Phase.VTOL_LAND]
    assert set(phases[2:-2]) == {Phase.FW_WAYPOINT}
    # VTOL takeoff and landing both happen at home.
    for item in (plan.items[0], plan.items[-1]):
        assert (item.north_m, item.east_m) == (0.0, 0.0)
    assert plan.items[-1].altitude_m == 0.0


def test_every_line_is_flown_exactly_once() -> None:
    plan = plan_survey(_area())
    assert sorted(plan.line_order) == list(range(_area().line_count))
    assert [line for line, _, _ in _survey_lines(plan)] == list(plan.line_order)


def test_wide_spacing_uses_plain_back_and_forth_order() -> None:
    plan = plan_survey(_area(line_spacing_m=120.0, cross_track_width_m=480.0))
    assert plan.line_interleave == 1
    assert plan.line_order == (0, 1, 2, 3, 4)


def test_tight_spacing_interleaves_lines_so_every_turn_fits() -> None:
    # 60 m spacing is below 2 x 57.2 m, so adjacent lines cannot be joined by
    # a single 180-degree turn at the modeled radius.
    area = _area()
    plan = plan_survey(area)
    assert plan.line_interleave == 2
    assert plan.line_order == (0, 2, 4, 1, 3, 5)
    for previous, current in zip(plan.line_order, plan.line_order[1:], strict=False):
        assert abs(current - previous) * area.line_spacing_m >= 2 * RADIUS


def test_consecutive_lines_alternate_direction_and_turn_at_same_end() -> None:
    plan = plan_survey(_area())
    lines = _survey_lines(plan)
    # Heading 90: lines run east-west and are offset north-south.
    for (_, start_a, end_a), (_, start_b, end_b) in zip(lines, lines[1:], strict=False):
        # Line B starts at the end where line A finished (a U-turn) ...
        assert start_b.east_m == pytest.approx(end_a.east_m)
        assert start_b.north_m != pytest.approx(end_a.north_m)
        # ... and runs the opposite way.
        assert (end_a.east_m - start_a.east_m) * (end_b.east_m - start_b.east_m) < 0


def test_lead_in_and_run_out_extend_one_turn_radius_beyond_line() -> None:
    plan = plan_survey(_area())
    fw = [i for i in plan.items if i.phase is Phase.FW_WAYPOINT and i.line_index is not None]
    for entry, start, end, exit_ in zip(fw[0::4], fw[1::4], fw[2::4], fw[3::4], strict=True):
        assert [entry.role, start.role, end.role, exit_.role] == [
            "line_entry",
            "line_start",
            "line_end",
            "line_exit",
        ]
        assert math.dist((entry.north_m, entry.east_m), (start.north_m, start.east_m)) == (
            pytest.approx(RADIUS)
        )
        assert math.dist((end.north_m, end.east_m), (exit_.north_m, exit_.east_m)) == (
            pytest.approx(RADIUS)
        )


def test_survey_points_fly_at_survey_altitude_and_transitions_at_transition_altitude() -> None:
    limits = SurveyLimits(survey_altitude_m=90.0, transition_altitude_m=50.0)
    plan = plan_survey(_area(), limits=limits)
    for item in plan.items:
        if item.line_index is not None:
            assert item.altitude_m == 90.0
    by_role = {item.role: item for item in plan.items}
    assert by_role["takeoff"].altitude_m == 50.0
    assert by_role["approach"].altitude_m == 50.0
    assert by_role["back_transition_start"].altitude_m == 50.0


def test_back_transition_is_on_straight_inbound_leg_toward_home() -> None:
    plan = plan_survey(_area())
    by_role = {item.role: item for item in plan.items}
    approach, to_mc = by_role["approach"], by_role["back_transition_start"]
    assert math.hypot(to_mc.north_m, to_mc.east_m) == pytest.approx(
        MODEL.back_transition_distance_m
    )
    assert math.hypot(approach.north_m, approach.east_m) == pytest.approx(
        MODEL.back_transition_distance_m + 2 * RADIUS
    )
    # Approach, back-transition start and home are collinear.
    cross = approach.north_m * to_mc.east_m - approach.east_m * to_mc.north_m
    assert cross == pytest.approx(0.0, abs=1e-6)


def test_area_too_close_to_home_for_forward_transition_is_rejected() -> None:
    with pytest.raises(SurveyPlanError, match="forward transition"):
        plan_survey(_area(start_north_m=50.0, start_east_m=0.0))


def test_area_beyond_advisory_radius_is_rejected_including_turn_overshoot() -> None:
    area = _area()
    accepted = plan_survey(area)
    farthest = max(
        math.hypot(i.north_m, i.east_m) for i in accepted.items if i.phase is Phase.FW_WAYPOINT
    )
    # Exactly enough for the farthest point but not its turn overshoot.
    with pytest.raises(SurveyPlanError, match="plus turn radius"):
        plan_survey(area, limits=SurveyLimits(max_distance_from_home_m=farthest + 1.0))
    plan_survey(area, limits=SurveyLimits(max_distance_from_home_m=farthest + RADIUS + 1.0))


def test_too_few_lines_for_interleave_is_rejected_not_silently_tight() -> None:
    # Three lines 40 m apart need a 3-line skip; no order keeps every turn >= 2R.
    with pytest.raises(SurveyPlanError, match="below 2 x turn radius"):
        plan_survey(_area(cross_track_width_m=80.0, line_spacing_m=40.0))


def test_single_line_survey_is_allowed() -> None:
    plan = plan_survey(_area(cross_track_width_m=0.0))
    assert plan.line_order == (0,)


@pytest.mark.parametrize(
    ("line_count", "interleave", "expected"),
    [
        (5, 1, (0, 1, 2, 3, 4)),
        (6, 2, (0, 2, 4, 1, 3, 5)),
        (7, 3, (0, 3, 6, 1, 4, 2, 5)),
        (2, 5, (0, 1)),
    ],
)
def test_interleaved_order(line_count, interleave, expected) -> None:
    assert interleaved_line_order(line_count, interleave) == expected


@pytest.mark.parametrize(
    "limits",
    [
        SurveyLimits(max_altitude_m=150.0, survey_altitude_m=140.0),
        SurveyLimits(survey_altitude_m=30.0),  # below fixed-wing floor
        SurveyLimits(transition_altitude_m=20.0),  # transition below fixed-wing floor
        SurveyLimits(max_distance_from_home_m=0.0),
        SurveyLimits(survey_altitude_m=float("nan")),
    ],
)
def test_invalid_limits_are_rejected(limits) -> None:
    with pytest.raises(ValueError):
        plan_survey(_area(), limits=limits)


@pytest.mark.parametrize(
    "model",
    [
        FighterModelInputs(cruise_airspeed_m_s=0.0),
        FighterModelInputs(planning_bank_deg=60.0),
        FighterModelInputs(forward_transition_distance_m=-1.0),
        FighterModelInputs(back_transition_distance_m=float("inf")),
    ],
)
def test_invalid_model_inputs_are_rejected(model) -> None:
    with pytest.raises(ValueError):
        plan_survey(_area(), model=model)


@pytest.mark.parametrize(
    "overrides",
    [
        {"line_length_m": 0.0},
        {"line_spacing_m": 0.0},
        {"cross_track_width_m": -1.0},
        {"start_north_m": float("nan")},
    ],
)
def test_invalid_area_is_rejected(overrides) -> None:
    with pytest.raises(ValueError):
        plan_survey(_area(**overrides))


def test_excessive_line_count_is_rejected() -> None:
    with pytest.raises(SurveyPlanError, match="planner limit"):
        plan_survey(_area(cross_track_width_m=10_000.0, line_spacing_m=10.0))


def test_plan_is_deterministic() -> None:
    assert plan_survey(_area()) == plan_survey(_area())
