"""Unit tests for the real-aircraft settings profile (no vehicle, no MAVSDK)."""

from __future__ import annotations

import dataclasses

import pytest

from x500.flight.aircraft_profile import (
    PROFILE_FIELDS,
    InputSource,
    ModelInput,
    ProfileNotReady,
    build_flight_settings,
    profile_findings,
)
from x500.flight.monitor_settings import X500_SITL_RETURN_SETTINGS, x500_sitl_monitor_settings
from x500.flight.settings import X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS
from x500.flight.x500_real_profile import X500_REAL_INPUTS

OWNER = InputSource.OWNER_CHOICE
FLIGHT = InputSource.FLIGHT_MEASUREMENT

# Test numbers only (not X500 values): each with an accepted source.
TEST_VALUES = {
    "max_relative_altitude_m": (25.0, OWNER),
    "min_waypoint_altitude_m": (5.0, OWNER),
    "max_distance_from_home_m": (80.0, OWNER),
    "max_speed_m_s": (4.0, OWNER),
    "max_waypoints": (10, OWNER),
    "min_battery_fraction": (0.45, OWNER),
    "max_telemetry_age_s": (3.0, InputSource.BENCH_MEASUREMENT),
    "start_timeout_s": (8.0, FLIGHT),
    "max_item_time_s": (45.0, OWNER),
    "max_mission_time_s": (240.0, OWNER),
    "completion_grace_s": (3.0, FLIGHT),
    "accept_timeout_s": (4.0, FLIGHT),
    "max_return_time_s": (90.0, OWNER),
    "disarm_timeout_s": (8.0, FLIGHT),
    "usable_flight_time_s": (600.0, FLIGHT),
}


def complete_inputs(**overrides: ModelInput) -> dict[str, ModelInput]:
    inputs = {
        name: ModelInput(value=value, source=source, reference="test log 0")
        for name, (value, source) in TEST_VALUES.items()
    }
    inputs.update(overrides)
    return inputs


def test_test_values_cover_every_field() -> None:
    assert set(TEST_VALUES) == set(PROFILE_FIELDS)


def test_complete_sourced_profile_builds_validated_settings() -> None:
    assert profile_findings(complete_inputs()) == ()
    settings = build_flight_settings(complete_inputs())
    assert settings.mission_limits.max_relative_altitude_m == 25.0
    assert settings.mission_limits.max_waypoints == 10
    assert settings.preflight_limits.min_battery_fraction == 0.45
    assert settings.return_settings.max_return_time_s == 90.0
    # One telemetry silence limit feeds all three watches.
    monitor = settings.monitor_settings_for(6)
    assert monitor.expected_item_count == 6
    assert monitor.max_mission_time_s == 240.0
    assert (
        monitor.max_telemetry_age_s
        == settings.preflight_limits.max_telemetry_age_s
        == settings.return_settings.max_telemetry_age_s
        == 3.0
    )


def test_monitor_factory_still_refuses_zero_items() -> None:
    settings = build_flight_settings(complete_inputs())
    with pytest.raises(ValueError):
        settings.monitor_settings_for(0)


def test_x500_real_profile_is_unfilled_and_refuses_with_every_field_listed() -> None:
    assert set(X500_REAL_INPUTS) == set(PROFILE_FIELDS)
    assert all(item.value is None and item.source is None for item in X500_REAL_INPUTS.values())
    with pytest.raises(ProfileNotReady) as excinfo:
        build_flight_settings(X500_REAL_INPUTS)
    reasons = excinfo.value.reasons
    for name in PROFILE_FIELDS:
        assert f"{name}: no value yet" in " ".join(r for r in reasons if r.startswith(name))
    # Every field also has a note saying what evidence fills it.
    assert all(item.note for item in X500_REAL_INPUTS.values())


@pytest.mark.parametrize("source", [InputSource.SITL_PLACEHOLDER, InputSource.CATALOGUE_CLAIM])
def test_sitl_placeholders_and_catalogue_claims_are_never_real_sources(source) -> None:
    for name, (value, _) in TEST_VALUES.items():
        inputs = complete_inputs(**{name: ModelInput(value, source, "x")})
        findings = profile_findings(inputs)
        assert any(f.startswith(f"{name}: source {source.value} not accepted") for f in findings)


def test_catalogue_hover_claim_cannot_set_usable_flight_time() -> None:
    claim = ModelInput(18 * 60.0, InputSource.CATALOGUE_CLAIM, "Holybro listing, 5000 mAh")
    with pytest.raises(ProfileNotReady, match="usable_flight_time_s: source catalogue_claim"):
        build_flight_settings(complete_inputs(usable_flight_time_s=claim))


def test_owner_choice_cannot_stand_in_for_measured_flight_time() -> None:
    findings = profile_findings(
        complete_inputs(usable_flight_time_s=ModelInput(900.0, OWNER, "2026-11-13"))
    )
    assert findings == (
        "usable_flight_time_s: source owner_choice not accepted (allowed: flight_measurement)",
    )


def test_mission_limits_must_be_owner_choices_not_measurements() -> None:
    findings = profile_findings(complete_inputs(max_speed_m_s=ModelInput(4.0, FLIGHT, "log 1")))
    assert findings == (
        "max_speed_m_s: source flight_measurement not accepted (allowed: owner_choice)",
    )


def test_missing_source_reference_and_value_are_all_reported_together() -> None:
    findings = profile_findings(complete_inputs(start_timeout_s=ModelInput()))
    assert findings == (
        "start_timeout_s: no value yet (s)",
        "start_timeout_s: no source recorded (allowed: flight_measurement, owner_choice)",
        "start_timeout_s: no reference (decision date, bench record or log name)",
    )


def test_blank_reference_refuses() -> None:
    findings = profile_findings(complete_inputs(start_timeout_s=ModelInput(8.0, FLIGHT, "   ")))
    assert findings == ("start_timeout_s: no reference (decision date, bench record or log name)",)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "8", [8]])
def test_non_numeric_or_non_finite_values_refuse(bad) -> None:
    findings = profile_findings(complete_inputs(start_timeout_s=ModelInput(bad, FLIGHT, "log")))
    assert findings == (f"start_timeout_s: value {bad!r} is not a finite number",)


def test_max_waypoints_must_be_an_integer() -> None:
    findings = profile_findings(complete_inputs(max_waypoints=ModelInput(10.0, OWNER, "x")))
    assert findings == ("max_waypoints: value 10.0 must be an integer",)


def test_missing_unknown_and_wrong_type_fields_refuse() -> None:
    inputs = complete_inputs()
    del inputs["disarm_timeout_s"]
    inputs["rtl_return_alt_m"] = ModelInput(60.0, OWNER, "x")
    inputs["accept_timeout_s"] = 4.0  # type: ignore[assignment]
    findings = profile_findings(inputs)
    assert "rtl_return_alt_m: unknown profile field" in findings
    assert "disarm_timeout_s: missing" in findings
    assert "accept_timeout_s: not a ModelInput" in findings


def test_existing_settings_validation_is_applied() -> None:
    # Item budget above mission budget is rejected by MonitorSettings.validate.
    findings = profile_findings(complete_inputs(max_item_time_s=ModelInput(300.0, OWNER, "x")))
    assert findings == (
        "inconsistent settings: max_item_time_s must not exceed max_mission_time_s",
    )
    findings = profile_findings(
        complete_inputs(min_waypoint_altitude_m=ModelInput(30.0, OWNER, "x"))
    )
    assert len(findings) == 1 and findings[0].startswith("inconsistent settings: Need 0 < min")


def test_mission_plus_return_budget_must_fit_usable_flight_time() -> None:
    # 240 + 90 = 330 s; equal passes, one second less refuses.
    fits = complete_inputs(usable_flight_time_s=ModelInput(330.0, FLIGHT, "log"))
    assert profile_findings(fits) == ()
    short = complete_inputs(usable_flight_time_s=ModelInput(329.0, FLIGHT, "log"))
    assert profile_findings(short) == (
        "max_mission_time_s + max_return_time_s = 330 s exceeds usable_flight_time_s = 329 s",
    )


def test_profile_does_not_touch_sitl_placeholders() -> None:
    before = (
        X500_SITL_MISSION_LIMITS,
        X500_SITL_PREFLIGHT_LIMITS,
        X500_SITL_RETURN_SETTINGS,
        x500_sitl_monitor_settings(5),
    )
    build_flight_settings(complete_inputs())
    after = (
        X500_SITL_MISSION_LIMITS,
        X500_SITL_PREFLIGHT_LIMITS,
        X500_SITL_RETURN_SETTINGS,
        x500_sitl_monitor_settings(5),
    )
    assert before == after
    assert X500_SITL_MISSION_LIMITS.max_relative_altitude_m == 30.0


def test_model_inputs_are_immutable() -> None:
    item = ModelInput(1.0, OWNER, "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.value = 2.0  # type: ignore[misc]
