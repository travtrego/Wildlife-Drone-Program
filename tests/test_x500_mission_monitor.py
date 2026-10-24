"""Behavioral tests for the X500 waypoint mission execution monitor."""

from __future__ import annotations

import math
from enum import Enum

import pytest

from x500.flight.mission_monitor import (
    EndReason,
    MissionExecutionMonitor,
    MissionSample,
    MissionState,
    MonitorSettings,
    Recommendation,
    normalize_flight_mode,
)
from x500.flight.monitor_settings import x500_sitl_monitor_settings

N = 4


def settings(**overrides) -> MonitorSettings:
    values = dict(
        expected_item_count=N,
        start_timeout_s=5.0,
        max_item_time_s=20.0,
        max_mission_time_s=60.0,
        max_telemetry_age_s=1.0,
    )
    values.update(overrides)
    return MonitorSettings(**values)


def sample(t, mode="MISSION", armed=True, in_air=True, current=0, total=N):
    return MissionSample(
        time_s=t,
        flight_mode=mode,
        armed=armed,
        in_air=in_air,
        current_item=current,
        total_items=total,
    )


def started(**overrides) -> MissionExecutionMonitor:
    monitor = MissionExecutionMonitor(settings(**overrides))
    monitor.start(0.0)
    return monitor


def fly_to_item(monitor, item, t):
    return monitor.update(sample(t, current=item))


# --- nominal path ---------------------------------------------------------


def test_nominal_mission_completes_after_ground_start():
    m = started()
    assert m.update(sample(0.2, in_air=False)).state is MissionState.IN_PROGRESS
    for i, t in enumerate([1.0, 1.5, 2.0, 2.5]):
        status = fly_to_item(m, i, t)
        assert status.state is MissionState.IN_PROGRESS
        assert status.current_item == i
    done = fly_to_item(m, N, 3.0)
    assert done.state is MissionState.COMPLETED
    assert done.reason is None and done.recommendation is Recommendation.NONE
    assert done.is_terminal


def test_completion_tolerates_hold_reported_at_final_item():
    m = started()
    m.update(sample(0.5, current=1))
    assert m.update(sample(1.0, mode="HOLD", current=N)).state is MissionState.COMPLETED


def test_terminal_status_is_sticky():
    m = started()
    m.update(sample(0.5, current=1))
    m.update(sample(1.0, current=N))
    later = m.update(sample(1.5, mode="POSCTL", current=N))
    assert later.state is MissionState.COMPLETED
    assert m.check(1000.0).state is MissionState.COMPLETED


def test_mavsdk_style_enum_modes_are_accepted():
    class FlightMode(Enum):
        MISSION = 10
        RETURN_TO_LAUNCH = 5

    m = started()
    assert (
        m.update(sample(0.5, mode=FlightMode.MISSION, current=1)).state is MissionState.IN_PROGRESS
    )
    end = m.update(sample(1.0, mode=FlightMode.RETURN_TO_LAUNCH, current=1))
    assert end.reason is EndReason.PX4_RECOVERY_MODE


# --- start phase ----------------------------------------------------------


def test_waits_through_transient_hold_until_mission_mode():
    m = started()
    assert m.update(sample(0.5, mode="HOLD", in_air=False)).state is MissionState.WAITING_FOR_START
    assert m.update(sample(1.0, in_air=False)).state is MissionState.IN_PROGRESS


def test_start_times_out_if_mission_mode_never_reported():
    m = started()
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        assert (
            m.update(sample(t, mode="HOLD", in_air=False)).state is MissionState.WAITING_FOR_START
        )
    end = m.update(sample(5.5, mode="HOLD", in_air=False))
    assert end.reason is EndReason.START_TIMEOUT
    assert end.recommendation is Recommendation.NONE


def test_mission_mode_while_disarmed_is_not_a_start():
    m = started()
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        status = m.update(sample(t, armed=False, in_air=False))
        assert status.state is MissionState.WAITING_FOR_START
    assert m.update(sample(5.1, armed=False, in_air=False)).reason is EndReason.START_TIMEOUT


def test_pilot_takeover_during_start_ends_attempt():
    m = started()
    assert m.update(sample(0.5, mode="MANUAL", in_air=False)).reason is EndReason.PILOT_TAKEOVER


# --- PX4 / pilot authority: the monitor yields and recommends nothing -------


@pytest.mark.parametrize("mode", ["MANUAL", "STABILIZED", "ALTCTL", "POSCTL", "ACRO", "RATTITUDE"])
def test_pilot_modes_end_with_no_recommendation(mode):
    m = started()
    m.update(sample(0.5, current=1))
    end = m.update(sample(1.0, mode=mode, current=1))
    assert end.state is MissionState.ENDED
    assert end.reason is EndReason.PILOT_TAKEOVER
    assert end.recommendation is Recommendation.NONE


@pytest.mark.parametrize("mode", ["RETURN_TO_LAUNCH", "LAND"])
def test_px4_recovery_modes_end_with_no_recommendation(mode):
    m = started()
    m.update(sample(0.5, current=2))
    end = m.update(sample(1.0, mode=mode, current=2))
    assert end.reason is EndReason.PX4_RECOVERY_MODE
    assert end.recommendation is Recommendation.NONE
    assert end.current_item == 2


def test_recovery_mode_at_final_item_is_not_completion():
    m = started()
    m.update(sample(0.5, current=1))
    assert m.update(sample(1.0, mode="RETURN_TO_LAUNCH", current=N)).reason is (
        EndReason.PX4_RECOVERY_MODE
    )


@pytest.mark.parametrize("mode", ["HOLD", "OFFBOARD", "TAKEOFF"])
def test_other_mode_before_completion_ends_as_mode_changed(mode):
    m = started()
    m.update(sample(0.5, current=1))
    end = m.update(sample(1.0, mode=mode, current=1))
    assert end.reason is EndReason.MODE_CHANGED
    assert end.recommendation is Recommendation.NONE


# --- vehicle state failures -----------------------------------------------


def test_disarm_mid_mission_ends():
    m = started()
    m.update(sample(0.5, current=1))
    assert m.update(sample(1.0, armed=False, current=1)).reason is EndReason.DISARMED


def test_landing_before_completion_ends():
    m = started()
    m.update(sample(0.5, current=1))
    end = m.update(sample(1.0, in_air=False, current=2))
    assert end.reason is EndReason.LANDED_EARLY


def test_final_item_without_ever_being_airborne_is_not_completion():
    m = started()
    m.update(sample(0.5, in_air=False, current=0))
    assert m.update(sample(1.0, in_air=False, current=N)).reason is EndReason.NEVER_AIRBORNE


# --- mission content / progress integrity ---------------------------------


def test_total_mismatch_means_mission_was_replaced():
    m = started()
    end = m.update(sample(0.5, current=0, total=N + 1))
    assert end.reason is EndReason.MISSION_CHANGED
    assert end.total_items == N + 1


def test_total_change_mid_mission_ends():
    m = started()
    m.update(sample(0.5, current=1))
    assert m.update(sample(1.0, current=1, total=2)).reason is EndReason.MISSION_CHANGED


def test_progress_regression_ends():
    m = started()
    m.update(sample(0.5, current=2))
    end = m.update(sample(1.0, current=1))
    assert end.reason is EndReason.PROGRESS_REGRESSED
    assert end.recommendation is Recommendation.NONE


# --- time budgets ---------------------------------------------------------


def test_stalled_item_recommends_rtl_but_does_not_command_it():
    m = started(max_telemetry_age_s=100.0)
    m.update(sample(0.0, current=1))
    assert m.update(sample(19.9, current=1)).state is MissionState.IN_PROGRESS
    end = m.update(sample(20.1, current=1))
    assert end.reason is EndReason.ITEM_STALLED
    assert end.recommendation is Recommendation.RETURN_TO_LAUNCH


def test_item_timer_resets_on_progress():
    m = started()
    t = 0.0
    for item in range(N):
        for _ in range(30):  # 15 s per item, below the 20 s item budget
            t += 0.5
            assert m.update(sample(t, current=item)).state is MissionState.IN_PROGRESS
    assert t == 60.0


def test_mission_timeout_recommends_rtl():
    m = started()
    t = 0.0
    item = 0
    status = None
    while t < 61.0:
        t += 0.5
        if t % 15 == 0 and item < N - 1:
            item += 1
        status = m.update(sample(t, current=item))
        if status.is_terminal:
            break
    assert status.reason is EndReason.MISSION_TIMEOUT
    assert status.recommendation is Recommendation.RETURN_TO_LAUNCH
    assert 60.0 < t <= 61.0


def test_silence_ends_as_telemetry_stale_without_recommendation():
    m = started()
    m.update(sample(0.5, current=1))
    assert m.check(1.4).state is MissionState.IN_PROGRESS
    end = m.check(1.6)
    assert end.reason is EndReason.TELEMETRY_STALE
    assert end.recommendation is Recommendation.NONE
    assert end.current_item == 1


def test_silence_during_start_is_stale_not_start_timeout():
    m = started()
    assert m.check(1.5).reason is EndReason.TELEMETRY_STALE


# --- malformed or misordered telemetry ------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        dict(armed=1),
        dict(in_air=None),
        dict(current=-1),
        dict(current=1.0),
        dict(total=True),
        dict(mode=""),
        dict(mode=None),
    ],
)
def test_malformed_samples_do_not_refresh_freshness(bad):
    m = started()
    m.update(sample(0.5, current=1))
    assert m.update(sample(1.0, **bad)).state is MissionState.IN_PROGRESS
    assert m.update(sample(1.6, **bad)).reason is EndReason.TELEMETRY_STALE


def test_out_of_order_sample_is_ignored():
    m = started()
    m.update(sample(1.0, current=2))
    assert m.update(sample(0.8, current=1)).state is MissionState.IN_PROGRESS
    assert m.status.current_item == 2


def test_item_beyond_total_is_rejected():
    m = started()
    assert m.update(sample(0.5, current=N + 1)).reason is EndReason.MISSION_CHANGED


@pytest.mark.parametrize("bad_time", [math.nan, math.inf])
def test_non_finite_times_raise(bad_time):
    m = started()
    with pytest.raises(ValueError):
        m.update(sample(bad_time))
    with pytest.raises(ValueError):
        m.check(bad_time)


def test_lifecycle_misuse_raises():
    m = MissionExecutionMonitor(settings())
    with pytest.raises(RuntimeError):
        m.update(sample(0.0))
    with pytest.raises(RuntimeError):
        m.check(0.0)
    m.start(0.0)
    with pytest.raises(RuntimeError):
        m.start(1.0)


# --- settings -------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        dict(expected_item_count=0),
        dict(expected_item_count=True),
        dict(expected_item_count=2.0),
        dict(start_timeout_s=0.0),
        dict(max_item_time_s=-1.0),
        dict(max_mission_time_s=math.inf),
        dict(max_telemetry_age_s=math.nan),
        dict(max_item_time_s=61.0, max_mission_time_s=60.0),
    ],
)
def test_invalid_settings_are_refused(overrides):
    with pytest.raises(ValueError):
        MissionExecutionMonitor(settings(**overrides))


def test_x500_placeholder_settings_validate():
    s = x500_sitl_monitor_settings(5)
    assert s.expected_item_count == 5
    assert s.max_item_time_s <= s.max_mission_time_s
    with pytest.raises(ValueError):
        x500_sitl_monitor_settings(0)


def test_normalize_flight_mode():
    assert normalize_flight_mode(" mission ") == "MISSION"
    assert normalize_flight_mode(42) == "UNKNOWN"


def test_mode_names_are_mavsdk_flight_modes():
    telemetry = pytest.importorskip("mavsdk.telemetry")
    from x500.flight.mission_monitor import (
        AUTOPILOT_RECOVERY_MODES,
        COMPLETION_MODES,
        PILOT_CONTROLLED_MODES,
    )

    names = {member.name for member in telemetry.FlightMode}
    assert PILOT_CONTROLLED_MODES | AUTOPILOT_RECOVERY_MODES | COMPLETION_MODES <= names
