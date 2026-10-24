import math
from enum import Enum

import pytest

from coyote.autonomy.action_gate import ActionKind, ActionRequest, evaluate_request
from coyote.autonomy.delegation import DelegationAuthority, GrantCommand, RevocationReason
from coyote.autonomy.telemetry import (
    Stream,
    TelemetryTracker,
    TelemetryTrackerConfig,
    battery_fraction_from_percent,
    evaluate_companion_request,
    normalize_flight_mode,
    observe_vehicle,
)

TAKEOFF = ActionRequest(ActionKind.TAKEOFF, altitude_m=10.0)
HOLD = ActionRequest(ActionKind.HOLD)


class FakeFlightMode(Enum):
    """Stand-in for mavsdk.telemetry.FlightMode (members expose ``.name``)."""

    HOLD = 3
    RETURN_TO_LAUNCH = 5


def fed(
    t: float,
    *,
    mode: object = "HOLD",
    armed: object = False,
    in_air: object = False,
    alt: object = 0.0,
    percent: object = 95.0,
    failsafe: object = False,
    tracker: TelemetryTracker | None = None,
) -> TelemetryTracker:
    tracker = tracker or TelemetryTracker()
    tracker.update_flight_mode(mode, t)
    tracker.update_armed(armed, t)
    tracker.update_in_air(in_air, t)
    tracker.update_position(alt, t)
    tracker.update_battery_percent(percent, t)
    tracker.update_failsafe(failsafe, t)
    return tracker


# --------------------------------------------------------------- conversions
@pytest.mark.parametrize(
    ("percent", "fraction"),
    [(0, 0.0), (50.0, 0.5), (85, 0.85), (100.0, 1.0)],
)
def test_battery_percent_converted_to_fraction(percent: object, fraction: float) -> None:
    assert battery_fraction_from_percent(percent) == pytest.approx(fraction)


@pytest.mark.parametrize("bad", [-0.1, 100.5, math.nan, math.inf, None, True, "80"])
def test_bad_battery_percent_is_unknown_not_clamped(bad: object) -> None:
    assert battery_fraction_from_percent(bad) is None


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        (FakeFlightMode.HOLD, "HOLD"),
        (FakeFlightMode.RETURN_TO_LAUNCH, "RETURN_TO_LAUNCH"),
        (" mission ", "MISSION"),
        ("", "UNKNOWN"),
        (None, "UNKNOWN"),
        (3, "UNKNOWN"),
    ],
)
def test_flight_mode_normalized(raw: object, name: str) -> None:
    assert normalize_flight_mode(raw) == name


# ------------------------------------------------------------------ snapshot
def test_complete_streams_build_snapshot() -> None:
    snap = fed(10.0, armed=True, in_air=True, alt=12.5, percent=64.0).snapshot(10.3)
    assert snap.flight_mode == "HOLD"
    assert snap.armed and snap.in_air
    assert snap.relative_altitude_m == 12.5
    assert snap.battery_remaining_fraction == pytest.approx(0.64)
    assert snap.telemetry_age_s == pytest.approx(0.3)
    assert snap.operator_delegated is False


def test_missing_stream_makes_snapshot_unknown_and_gate_rejects() -> None:
    tracker = TelemetryTracker()
    tracker.update_flight_mode("HOLD", 1.0)
    tracker.update_armed(True, 1.0)
    assert set(tracker.missing_streams()) == {Stream.IN_AIR, Stream.POSITION, Stream.BATTERY}
    snap = tracker.snapshot(1.0)
    assert math.isinf(snap.telemetry_age_s)
    assert not evaluate_request(HOLD, snap).allowed


def test_oldest_stream_sets_age() -> None:
    tracker = fed(10.0)
    for t in (10.5, 11.0, 11.5):  # every stream but battery keeps arriving
        tracker.update_flight_mode("HOLD", t)
        tracker.update_armed(False, t)
        tracker.update_in_air(False, t)
        tracker.update_position(0.0, t)
    assert tracker.snapshot(11.5).telemetry_age_s == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("method", "bad"),
    [
        ("update_armed", 1),
        ("update_armed", None),
        ("update_in_air", "yes"),
        ("update_position", math.nan),
        ("update_position", True),
    ],
)
def test_malformed_value_forgets_stream(method: str, bad: object) -> None:
    tracker = fed(1.0)
    getattr(tracker, method)(bad, 1.1)
    assert tracker.missing_streams()
    assert math.isinf(tracker.snapshot(1.1).telemetry_age_s)


def test_out_of_order_update_is_ignored() -> None:
    tracker = fed(5.0, armed=True)
    tracker.update_armed(False, 4.0)  # delayed older message
    snap = tracker.snapshot(5.1)
    assert snap.armed is True
    assert snap.telemetry_age_s == pytest.approx(0.1)


def test_bad_out_of_range_battery_is_unknown_and_blocks_takeoff() -> None:
    tracker, auth = delegated_on_ground()
    fed(1.5, armed=True, percent=140.0, tracker=tracker)
    assert tracker.snapshot(1.5).battery_remaining_fraction is None
    decision = evaluate_companion_request(TAKEOFF, tracker, auth, 1.5)
    assert not decision.allowed
    assert "unknown" in decision.reasons[0]


@pytest.mark.parametrize("bad_time", [math.nan, math.inf])
def test_non_finite_update_time_raises(bad_time: float) -> None:
    with pytest.raises(ValueError):
        TelemetryTracker().update_armed(True, bad_time)


def test_config_rejects_bad_failsafe_age() -> None:
    with pytest.raises(ValueError):
        TelemetryTracker(TelemetryTrackerConfig(max_failsafe_age_s=0.0))


# ------------------------------------------------------------------ failsafe
def test_failsafe_unknown_until_reported_and_when_stale() -> None:
    tracker = TelemetryTracker()
    assert tracker.failsafe_active(0.0) is None
    tracker.update_failsafe(False, 1.0)
    assert tracker.failsafe_active(1.5) is False
    assert tracker.failsafe_active(2.5) is None  # older than 1.0 s placeholder
    tracker.update_failsafe("ok", 3.0)  # non-bool is unknown
    assert tracker.failsafe_active(3.0) is None


def test_grant_refused_without_failsafe_source() -> None:
    tracker = fed(1.0, failsafe=None)
    auth = DelegationAuthority()
    observe_vehicle(tracker, auth, 1.0)
    result = auth.request_grant(GrantCommand(1, 1.0), 1.0)
    assert not result.accepted
    assert "failsafe" in result.reason.lower()


# ---------------------------------------------------------------- end to end
def delegated_on_ground(t: float = 1.0) -> tuple[TelemetryTracker, DelegationAuthority]:
    tracker = fed(t)
    auth = DelegationAuthority()
    observe_vehicle(tracker, auth, t)
    assert auth.request_grant(GrantCommand(1, t), t).accepted
    return tracker, auth


def test_takeoff_allowed_after_operator_arms_with_percent_battery() -> None:
    tracker, auth = delegated_on_ground()
    assert not evaluate_companion_request(TAKEOFF, tracker, auth, 1.1).allowed  # disarmed
    fed(1.5, armed=True, percent=85.0, tracker=tracker)  # operator arms
    decision = evaluate_companion_request(TAKEOFF, tracker, auth, 1.6)
    assert decision.allowed, decision.reasons


def test_low_percent_battery_blocks_takeoff() -> None:
    tracker, auth = delegated_on_ground()
    fed(1.5, armed=True, percent=70.0, tracker=tracker)
    decision = evaluate_companion_request(TAKEOFF, tracker, auth, 1.6)
    assert not decision.allowed
    assert "below" in decision.reasons[0]


def test_one_silent_stream_revokes_with_link_lost_alert() -> None:
    tracker, auth = delegated_on_ground()
    for t in (1.5, 2.0, 2.5):  # battery stream goes silent after t=1.0
        tracker.update_flight_mode("HOLD", t)
        tracker.update_armed(False, t)
        tracker.update_in_air(False, t)
        tracker.update_position(0.0, t)
        tracker.update_failsafe(False, t)
    assert not evaluate_companion_request(HOLD, tracker, auth, 2.5).allowed
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.TELEMETRY_LINK_LOST


def test_failsafe_report_revokes_and_stays_revoked() -> None:
    tracker, auth = delegated_on_ground()
    fed(1.5, armed=True, failsafe=True, tracker=tracker)
    observe_vehicle(tracker, auth, 1.5)
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.PX4_FAILSAFE
    fed(2.0, armed=True, failsafe=False, tracker=tracker)  # failsafe clears
    assert not evaluate_companion_request(TAKEOFF, tracker, auth, 2.0).allowed


def test_failsafe_source_going_quiet_revokes() -> None:
    tracker, auth = delegated_on_ground()
    for t in (1.5, 2.0, 2.5):  # vehicle streams fresh, failsafe source silent
        tracker.update_flight_mode("HOLD", t)
        tracker.update_armed(True, t)
        tracker.update_in_air(False, t)
        tracker.update_position(0.0, t)
        tracker.update_battery_percent(95.0, t)
    observe_vehicle(tracker, auth, 2.5)
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.FAILSAFE_STATE_UNKNOWN


def test_recovery_mode_enum_revokes() -> None:
    tracker, auth = delegated_on_ground()
    fed(1.5, mode=FakeFlightMode.RETURN_TO_LAUNCH, armed=True, tracker=tracker)
    assert not evaluate_companion_request(HOLD, tracker, auth, 1.5).allowed
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.PX4_RECOVERY_MODE


def test_gate_mode_names_exist_in_mavsdk_enum() -> None:
    """Skipped in CI (no MAVSDK); guards against a renamed or misspelt mode."""
    telemetry = pytest.importorskip("mavsdk.telemetry")
    from coyote.autonomy.action_gate import (
        AUTOPILOT_RECOVERY_MODES,
        COMPANION_DELEGATED_MODES,
        PILOT_CONTROLLED_MODES,
    )

    names = {normalize_flight_mode(m) for m in telemetry.FlightMode}
    assert PILOT_CONTROLLED_MODES | AUTOPILOT_RECOVERY_MODES | COMPANION_DELEGATED_MODES <= names
