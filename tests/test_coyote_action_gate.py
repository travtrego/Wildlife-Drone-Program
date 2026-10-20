import math
from dataclasses import replace

import pytest

from coyote.autonomy.action_gate import (
    ActionKind,
    ActionRequest,
    AdvisoryLimits,
    VehicleSnapshot,
    Verdict,
    evaluate_request,
)

FLYING = VehicleSnapshot(
    flight_mode="HOLD",
    armed=True,
    in_air=True,
    relative_altitude_m=20.0,
    battery_remaining_fraction=0.80,
    telemetry_age_s=0.1,
    operator_delegated=True,
)
GOTO_OK = ActionRequest(ActionKind.GOTO_LOCAL, north_m=30.0, east_m=-20.0, altitude_m=25.0)
ALL_ACTIONS = [
    ActionRequest(ActionKind.HOLD),
    ActionRequest(ActionKind.RETURN_TO_LAUNCH),
    ActionRequest(ActionKind.LAND),
    GOTO_OK,
]


@pytest.mark.parametrize("mode", ["HOLD", "MISSION", "OFFBOARD", "offboard "])
def test_goto_within_limits_allowed_in_delegated_modes(mode) -> None:
    decision = evaluate_request(GOTO_OK, replace(FLYING, flight_mode=mode))
    assert decision.allowed
    assert decision.recommended is None


@pytest.mark.parametrize("mode", ["MANUAL", "STABILIZED", "ALTCTL", "POSCTL", "ACRO"])
@pytest.mark.parametrize("request_", ALL_ACTIONS)
def test_pilot_override_rejects_every_request(mode, request_) -> None:
    decision = evaluate_request(request_, replace(FLYING, flight_mode=mode))
    assert decision.verdict is Verdict.REJECT
    assert "pilot" in decision.reasons[0]


@pytest.mark.parametrize("mode", ["RETURN_TO_LAUNCH", "LAND"])
@pytest.mark.parametrize("request_", ALL_ACTIONS)
def test_companion_never_overrides_px4_recovery(mode, request_) -> None:
    decision = evaluate_request(request_, replace(FLYING, flight_mode=mode))
    assert not decision.allowed
    assert "recovery" in decision.reasons[0]


@pytest.mark.parametrize("mode", ["UNKNOWN", "", "TAKEOFF", "FOLLOW_ME", "READY"])
def test_undelegated_or_unknown_modes_rejected(mode) -> None:
    assert not evaluate_request(GOTO_OK, replace(FLYING, flight_mode=mode)).allowed


@pytest.mark.parametrize("request_", ALL_ACTIONS)
def test_missing_operator_delegation_rejects_every_request(request_) -> None:
    decision = evaluate_request(request_, replace(FLYING, operator_delegated=False))
    assert not decision.allowed
    assert "delegated" in decision.reasons[0]


def test_operator_delegation_defaults_to_false() -> None:
    snapshot = VehicleSnapshot("HOLD", True, True, 20.0, 0.8, 0.1)
    assert not evaluate_request(ActionRequest(ActionKind.HOLD), snapshot).allowed


@pytest.mark.parametrize("age", [1.5, math.inf, math.nan, -0.1])
@pytest.mark.parametrize("request_", ALL_ACTIONS)
def test_stale_or_invalid_telemetry_rejects_every_request(age, request_) -> None:
    assert not evaluate_request(request_, replace(FLYING, telemetry_age_s=age)).allowed


def test_stale_check_precedes_pilot_check() -> None:
    snapshot = replace(FLYING, flight_mode="POSCTL", telemetry_age_s=5.0)
    assert "stale" in evaluate_request(GOTO_OK, snapshot).reasons[0]


@pytest.mark.parametrize(
    "snapshot",
    [replace(FLYING, armed=False, in_air=False), replace(FLYING, in_air=False)],
)
def test_ground_requests_rejected(snapshot) -> None:
    assert not evaluate_request(ActionRequest(ActionKind.HOLD), snapshot).allowed


@pytest.mark.parametrize("kind", [ActionKind.HOLD, ActionKind.RETURN_TO_LAUNCH, ActionKind.LAND])
def test_de_escalation_allowed_even_with_low_or_unknown_battery(kind) -> None:
    for battery in (0.05, None):
        snapshot = replace(FLYING, battery_remaining_fraction=battery)
        assert evaluate_request(ActionRequest(kind), snapshot).allowed


@pytest.mark.parametrize("battery", [0.39, 0.0, None, math.nan])
def test_goto_below_reserve_or_unknown_battery_recommends_rtl(battery) -> None:
    decision = evaluate_request(GOTO_OK, replace(FLYING, battery_remaining_fraction=battery))
    assert not decision.allowed
    assert decision.recommended is ActionKind.RETURN_TO_LAUNCH


def test_goto_battery_reserve_boundary_is_inclusive() -> None:
    assert evaluate_request(GOTO_OK, replace(FLYING, battery_remaining_fraction=0.40)).allowed


@pytest.mark.parametrize("battery", [5.0, 40.0, 80.0, 100.0, 1.01, -0.01, math.inf])
def test_goto_rejects_battery_outside_fraction_range(battery) -> None:
    # MAVSDK remaining_percent is 0-100; passing it unconverted must not
    # silently bypass the reserve check (5.0 would otherwise read as "above 0.40").
    decision = evaluate_request(GOTO_OK, replace(FLYING, battery_remaining_fraction=battery))
    assert not decision.allowed
    assert decision.recommended is ActionKind.RETURN_TO_LAUNCH


def test_goto_full_battery_fraction_is_allowed() -> None:
    assert evaluate_request(GOTO_OK, replace(FLYING, battery_remaining_fraction=1.0)).allowed


@pytest.mark.parametrize(
    ("north", "east", "alt", "fragment"),
    [
        (0.0, 0.0, 61.0, "altitude"),
        (0.0, 0.0, 4.9, "altitude"),
        (120.0, 91.0, 25.0, "from home"),  # hypot = 150.6 m
        (0.0, math.nan, 25.0, "non-finite"),
        (math.inf, 0.0, 25.0, "non-finite"),
    ],
)
def test_goto_outside_advisory_envelope_rejected(north, east, alt, fragment) -> None:
    request = ActionRequest(ActionKind.GOTO_LOCAL, north_m=north, east_m=east, altitude_m=alt)
    decision = evaluate_request(request, FLYING)
    assert not decision.allowed
    assert any(fragment in reason for reason in decision.reasons)


def test_goto_reports_all_envelope_violations_and_recommends_hold() -> None:
    request = ActionRequest(ActionKind.GOTO_LOCAL, north_m=500.0, altitude_m=200.0)
    decision = evaluate_request(request, FLYING)
    assert len(decision.reasons) == 2
    assert decision.recommended is ActionKind.HOLD


def test_goto_envelope_boundaries_are_inclusive() -> None:
    for request in (
        ActionRequest(ActionKind.GOTO_LOCAL, north_m=150.0, altitude_m=60.0),
        ActionRequest(ActionKind.GOTO_LOCAL, east_m=-150.0, altitude_m=5.0),
    ):
        assert evaluate_request(request, FLYING).allowed


@pytest.mark.parametrize(
    "limits",
    [
        AdvisoryLimits(max_altitude_m=150.0),
        AdvisoryLimits(min_altitude_m=0.0),
        AdvisoryLimits(min_altitude_m=70.0),
        AdvisoryLimits(max_distance_from_home_m=0.0),
        AdvisoryLimits(min_battery_fraction_for_goto=1.0),
        AdvisoryLimits(max_telemetry_age_s=0.0),
        AdvisoryLimits(max_distance_from_home_m=math.inf),
    ],
)
def test_invalid_advisory_limits_raise(limits) -> None:
    with pytest.raises(ValueError):
        evaluate_request(GOTO_OK, FLYING, limits)


# --- Companion-requested takeoff (owner decision 2026-10-20, option 1) -------

ARMED_ON_GROUND = replace(
    FLYING, in_air=False, relative_altitude_m=0.0, battery_remaining_fraction=0.95
)
TAKEOFF = ActionRequest(ActionKind.TAKEOFF, altitude_m=20.0)


@pytest.mark.parametrize("mode", ["HOLD", "MISSION", "hold"])
def test_takeoff_allowed_when_armed_delegated_on_ground(mode) -> None:
    decision = evaluate_request(TAKEOFF, replace(ARMED_ON_GROUND, flight_mode=mode))
    assert decision.allowed
    assert decision.recommended is None


@pytest.mark.parametrize(
    "snapshot",
    [
        replace(ARMED_ON_GROUND, armed=False),  # companion never arms
        replace(ARMED_ON_GROUND, operator_delegated=False),
        replace(ARMED_ON_GROUND, in_air=True),  # already flying
        replace(ARMED_ON_GROUND, flight_mode="OFFBOARD"),
        replace(ARMED_ON_GROUND, flight_mode="POSCTL"),
        replace(ARMED_ON_GROUND, flight_mode="LAND"),
        replace(ARMED_ON_GROUND, flight_mode="TAKEOFF"),
        replace(ARMED_ON_GROUND, telemetry_age_s=1.5),
        replace(ARMED_ON_GROUND, telemetry_age_s=math.nan),
        replace(ARMED_ON_GROUND, battery_remaining_fraction=None),
        replace(ARMED_ON_GROUND, battery_remaining_fraction=math.nan),
        replace(ARMED_ON_GROUND, battery_remaining_fraction=0.79),
        replace(ARMED_ON_GROUND, battery_remaining_fraction=95.0),
    ],
)
def test_takeoff_rejected_when_preconditions_fail(snapshot) -> None:
    decision = evaluate_request(TAKEOFF, snapshot)
    assert decision.verdict is Verdict.REJECT
    assert decision.reasons


def test_takeoff_battery_boundary_is_inclusive() -> None:
    snapshot = replace(ARMED_ON_GROUND, battery_remaining_fraction=0.80)
    assert evaluate_request(TAKEOFF, snapshot).allowed


@pytest.mark.parametrize("altitude", [4.9, 60.1, -5.0, math.nan, math.inf])
def test_takeoff_altitude_outside_advisory_limits_rejected(altitude) -> None:
    request = ActionRequest(ActionKind.TAKEOFF, altitude_m=altitude)
    assert not evaluate_request(request, ARMED_ON_GROUND).allowed


@pytest.mark.parametrize("altitude", [5.0, 60.0])
def test_takeoff_altitude_boundaries_inclusive(altitude) -> None:
    request = ActionRequest(ActionKind.TAKEOFF, altitude_m=altitude)
    assert evaluate_request(request, ARMED_ON_GROUND).allowed


def test_ground_still_rejects_every_non_takeoff_action() -> None:
    for kind in (ActionKind.HOLD, ActionKind.RETURN_TO_LAUNCH, ActionKind.LAND):
        assert not evaluate_request(ActionRequest(kind), ARMED_ON_GROUND).allowed
    assert not evaluate_request(GOTO_OK, ARMED_ON_GROUND).allowed


def test_no_arm_action_exists() -> None:
    assert not any("arm" in kind.value for kind in ActionKind)


@pytest.mark.parametrize(
    "limits",
    [
        AdvisoryLimits(min_battery_fraction_for_takeoff=0.0),
        AdvisoryLimits(min_battery_fraction_for_takeoff=1.1),
        AdvisoryLimits(min_battery_fraction_for_takeoff=math.nan),
        AdvisoryLimits(min_battery_fraction_for_goto=0.5, min_battery_fraction_for_takeoff=0.45),
    ],
)
def test_invalid_takeoff_reserve_raises(limits) -> None:
    with pytest.raises(ValueError):
        evaluate_request(TAKEOFF, ARMED_ON_GROUND, limits)
