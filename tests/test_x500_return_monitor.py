"""Behavioral tests for the return/landing watch after an RTL request.

Plain samples and explicit times only. None of this is evidence of how PX4
SITL reports a return, landing or disarm.
"""

from __future__ import annotations

import math

import pytest

from x500.flight.mission_monitor import MissionSample
from x500.flight.monitor_settings import X500_SITL_RETURN_SETTINGS
from x500.flight.return_monitor import (
    ReturnEndReason,
    ReturnLandingMonitor,
    ReturnSettings,
    ReturnState,
)

T0 = 100.0


def settings(**overrides) -> ReturnSettings:
    values = dict(
        accept_timeout_s=5.0, max_return_time_s=60.0, disarm_timeout_s=10.0, max_telemetry_age_s=2.0
    )
    values.update(overrides)
    return ReturnSettings(**values)


def sample(t, mode="RETURN_TO_LAUNCH", armed=True, in_air=True):
    return MissionSample(
        time_s=T0 + t, flight_mode=mode, armed=armed, in_air=in_air, current_item=3, total_items=3
    )


def started(**overrides) -> ReturnLandingMonitor:
    m = ReturnLandingMonitor(settings(**overrides))
    m.start(T0)
    return m


def nominal(m: ReturnLandingMonitor) -> None:
    m.update(sample(0.5, mode="HOLD"))
    m.update(sample(1.0))
    m.update(sample(20.0, mode="LAND"))
    m.update(sample(25.0, mode="LAND", in_air=False))


# --- nominal -----------------------------------------------------------------


def test_rtl_land_disarm_is_landed() -> None:
    m = started()
    nominal(m)
    assert m.status.state is ReturnState.LANDED_ARMED
    status = m.update(sample(27.0, mode="LAND", armed=False, in_air=False))
    assert status.state is ReturnState.LANDED and status.landed_and_disarmed
    assert status.is_terminal and status.reason is None


def test_terminal_result_is_sticky() -> None:
    m = started()
    nominal(m)
    m.update(sample(27.0, armed=False, in_air=False))
    assert m.update(sample(28.0, mode="POSCTL")).state is ReturnState.LANDED
    assert m.check(T0 + 1000.0).state is ReturnState.LANDED


def test_mode_is_ignored_on_the_ground() -> None:
    m = started()
    nominal(m)
    # PX4's post-landing mode is unobserved; HOLD on the ground is not MODE_CHANGED.
    assert m.update(sample(26.0, mode="HOLD", in_air=False)).state is ReturnState.LANDED_ARMED
    assert m.update(sample(27.0, mode="HOLD", armed=False, in_air=False)).landed_and_disarmed


def test_land_detector_bounce_returns_to_returning() -> None:
    m = started()
    nominal(m)
    assert m.update(sample(26.0, mode="LAND")).state is ReturnState.RETURNING
    # The disarm clock restarts at the second touchdown.
    for t in (30.0, 32.0, 34.0, 36.0, 38.0, 39.0):
        m.update(sample(t, mode="LAND", in_air=False))
    assert m.check(T0 + 39.9).state is ReturnState.LANDED_ARMED
    assert m.update(sample(39.5, armed=False, in_air=False)).landed_and_disarmed


# --- request not acted on -------------------------------------------------------


def test_waiting_in_hold_until_accept_timeout() -> None:
    m = started()
    assert m.update(sample(4.0, mode="HOLD")).state is ReturnState.WAITING_FOR_RETURN
    status = m.check(T0 + 5.1)
    assert status.reason is ReturnEndReason.RETURN_NOT_ACCEPTED


def test_accept_timeout_with_no_samples_at_all_reports_stale_first() -> None:
    m = started(accept_timeout_s=5.0, max_telemetry_age_s=2.0)
    assert m.check(T0 + 2.1).reason is ReturnEndReason.TELEMETRY_STALE


def test_unexpected_mode_before_return_ends_watch() -> None:
    m = started()
    status = m.update(sample(1.0, mode="OFFBOARD"))
    assert status.reason is ReturnEndReason.MODE_CHANGED


def test_on_ground_before_px4_reported_return() -> None:
    m = started()
    status = m.update(sample(1.0, mode="HOLD", in_air=False))
    assert status.reason is ReturnEndReason.LANDED_WITHOUT_RETURN


# --- PX4 or pilot changes the plan ---------------------------------------------------


@pytest.mark.parametrize("when", ["waiting", "returning", "landed"])
def test_pilot_mode_ends_watch_in_every_state(when) -> None:
    m = started()
    if when != "waiting":
        m.update(sample(1.0))
    if when == "landed":
        m.update(sample(20.0, in_air=False))
    status = m.update(sample(21.0, mode="POSCTL", in_air=when != "landed"))
    assert status.reason is ReturnEndReason.PILOT_TAKEOVER


@pytest.mark.parametrize("mode", ["HOLD", "MISSION", "OFFBOARD"])
def test_px4_leaving_rtl_while_airborne_is_mode_changed(mode) -> None:
    m = started()
    m.update(sample(1.0))
    status = m.update(sample(5.0, mode=mode))
    assert status.reason is ReturnEndReason.MODE_CHANGED and mode in status.detail


def test_rtl_to_land_handover_is_still_returning() -> None:
    m = started()
    m.update(sample(1.0))
    assert m.update(sample(15.0, mode="LAND")).state is ReturnState.RETURNING


@pytest.mark.parametrize("returning", [False, True])
def test_disarmed_while_airborne(returning) -> None:
    m = started()
    if returning:
        m.update(sample(1.0))
    status = m.update(sample(2.0, mode="RETURN_TO_LAUNCH", armed=False, in_air=True))
    assert status.reason is ReturnEndReason.DISARMED_IN_AIR


# --- landing without disarm, timeouts, telemetry -------------------------------------


def test_landed_but_never_disarmed() -> None:
    m = started(disarm_timeout_s=10.0)
    nominal(m)  # touchdown at +25 s
    for t in (27.0, 29.0, 31.0, 33.0, 35.0):
        m.update(sample(t, mode="LAND", in_air=False))
    assert m.status.state is ReturnState.LANDED_ARMED
    status = m.check(T0 + 35.1)
    assert status.reason is ReturnEndReason.LANDED_NOT_DISARMED


def test_return_that_never_lands_times_out() -> None:
    m = started(max_return_time_s=60.0)
    for t in range(1, 61):
        m.update(sample(float(t)))
    assert m.status.state is ReturnState.RETURNING
    assert m.check(T0 + 60.1).reason is ReturnEndReason.RETURN_TIMEOUT


def test_silence_while_returning_is_stale() -> None:
    m = started()
    m.update(sample(1.0))
    assert m.check(T0 + 3.0).state is ReturnState.RETURNING
    assert m.check(T0 + 3.1).reason is ReturnEndReason.TELEMETRY_STALE


@pytest.mark.parametrize(
    "bad",
    [
        dict(armed=None),
        dict(in_air="yes"),
        dict(mode=None),
        dict(armed=1),
    ],
)
def test_malformed_samples_do_not_refresh_freshness(bad) -> None:
    m = started()
    m.update(sample(1.0))
    m.update(sample(2.5, **bad))
    assert m.status.state is ReturnState.RETURNING
    assert m.check(T0 + 3.1).reason is ReturnEndReason.TELEMETRY_STALE


def test_pre_request_and_out_of_order_samples_are_ignored() -> None:
    m = started()
    # A sample taken before the request (vehicle on the ground earlier) is ignored.
    assert m.update(sample(-1.0, mode="HOLD", in_air=False)).state is ReturnState.WAITING_FOR_RETURN
    m.update(sample(2.0))
    assert m.update(sample(1.5, mode="OFFBOARD")).state is ReturnState.RETURNING


def test_mavsdk_style_enum_modes_are_normalized() -> None:
    class Mode:
        name = "Return_To_Launch"

    m = started()
    assert m.update(sample(1.0, mode=Mode())).state is ReturnState.RETURNING


# --- API misuse and settings -------------------------------------------------------


def test_must_start_once_before_use() -> None:
    m = ReturnLandingMonitor(settings())
    with pytest.raises(RuntimeError):
        m.update(sample(1.0))
    with pytest.raises(RuntimeError):
        m.check(T0)
    m.start(T0)
    with pytest.raises(RuntimeError):
        m.start(T0 + 1.0)


@pytest.mark.parametrize("bad", [math.nan, math.inf, True])
def test_non_finite_times_are_rejected(bad) -> None:
    m = ReturnLandingMonitor(settings())
    with pytest.raises(ValueError):
        m.start(bad)


@pytest.mark.parametrize(
    "overrides",
    [
        dict(accept_timeout_s=0.0),
        dict(max_return_time_s=-1.0),
        dict(disarm_timeout_s=math.nan),
        dict(max_telemetry_age_s=True),
        dict(accept_timeout_s=70.0),
        dict(disarm_timeout_s=70.0),
    ],
)
def test_invalid_settings_are_refused(overrides) -> None:
    with pytest.raises(ValueError):
        ReturnLandingMonitor(settings(**overrides))


def test_x500_sitl_placeholders_are_valid() -> None:
    X500_SITL_RETURN_SETTINGS.validate()
    assert X500_SITL_RETURN_SETTINGS.max_return_time_s == 120.0
