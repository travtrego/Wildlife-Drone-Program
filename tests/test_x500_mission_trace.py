"""Tests for the read-only mission trace.

Plain values, fake clocks and the in-memory fake vehicle only. None of this is
evidence of PX4 SITL stream rates, modes or timings.
"""

from __future__ import annotations

import asyncio

import pytest
from test_x500_mission_telemetry import (  # pytest puts tests/ on sys.path
    FAST_RETURN,
    LIMITS,
    MISSION_MODULE,
    SQUARE,
    FakeVehicle,
    _fly,
    settings,
)

from simulation.mavsdk.waypoint_mission_flight import fly_waypoint_mission
from x500.flight.mission_monitor import (
    EndReason,
    MissionExecutionMonitor,
    MissionState,
    MissionStatus,
    MonitorSettings,
)
from x500.flight.mission_telemetry import MissionStream, MissionTelemetryCombiner, run_monitor
from x500.flight.mission_trace import MissionTrace

F, A, AIR, P = (
    MissionStream.FLIGHT_MODE,
    MissionStream.ARMED,
    MissionStream.IN_AIR,
    MissionStream.PROGRESS,
)


def _settings(**overrides) -> MonitorSettings:
    values = dict(
        expected_item_count=3,
        start_timeout_s=5.0,
        max_item_time_s=10.0,
        max_mission_time_s=60.0,
        max_telemetry_age_s=2.0,
    )
    values.update(overrides)
    return MonitorSettings(**values)


def _nominal_trace(emit=None) -> MissionTrace:
    """Pre-start ground state, start at t=100, takeoff, three items, final HOLD race."""

    t = MissionTrace(emit=emit)
    for s, v in ((F, "HOLD"), (A, False), (AIR, False), (P, (0, 3))):
        t.observe(s, v, 98.0)
    t.observe(A, True, 99.5)
    t.mark_start(100.0)
    for second in range(101, 131):  # 1 Hz periodic streams, unchanged values are counted only
        now = float(second)
        t.observe(F, "MISSION" if second < 128 else "HOLD", now)
        t.observe(A, True, now)
        t.observe(AIR, second >= 102, now)
    t.observe(P, (1, 3), 109.0)
    t.observe(P, (2, 3), 117.5)
    t.observe(P, (3, 3), 128.5)  # completion arrives after HOLD (2026-11-01 A0 order)
    return t


def test_events_record_changes_only_with_times_relative_to_start() -> None:
    lines: list[str] = []
    trace = _nominal_trace(emit=lines.append)
    mode_events = [e for e in trace.events if e.source == "flight_mode"]
    assert [e.text for e in mode_events] == ["HOLD", "MISSION", "HOLD"]
    assert any("+28.00s] flight_mode: HOLD" in line for line in lines)
    assert any("pre-start] flight_mode: HOLD" in line for line in lines)
    # Order of the final HOLD and final progress is preserved for diagnosis.
    order = [(e.source, e.text) for e in trace.events if e.time_s >= 128.0]
    assert order.index(("flight_mode", "HOLD")) < order.index(("mission_progress", "3/3"))


def test_item_durations_time_first_item_from_start_request() -> None:
    trace = _nominal_trace()
    assert trace.item_durations() == [(0, 9.0), (1, 8.5), (2, 11.0)]
    assert trace.mission_duration_s() == pytest.approx(28.5)
    assert trace.first_event_after_start("flight_mode", "MISSION") == pytest.approx(1.0)
    assert trace.first_event_after_start("in_air", "True") == pytest.approx(2.0)


def test_stream_stats_report_count_rate_and_largest_gap() -> None:
    trace = MissionTrace()
    for now in (0.0, 1.0, 2.0, 5.0):
        trace.observe(F, "MISSION", now)
    count, rate, gap = trace.stream_stats(F)
    assert count == 4
    assert rate == pytest.approx(3 / 5.0)
    assert gap == pytest.approx(3.0)
    assert trace.stream_stats(P) == (0, None, None)


def test_summary_flags_observations_beyond_placeholders_without_failing() -> None:
    lines = _nominal_trace().summary_lines(_settings())
    text = "\n".join(lines)
    assert "longest item          11.00 s of 10 s (110%)  EXCEEDS PLACEHOLDER" in text
    assert "start (MISSION mode)  1.00 s of 5 s (20%)" in text
    assert "whole mission         28.50 s of 60 s (48%)" in text
    assert "periodic gap (run)    1.00 s of 2 s (50%)" in text
    assert "not validated limits" in lines[0]


def test_summary_without_start_reports_not_observed() -> None:
    trace = MissionTrace()
    trace.observe(F, "HOLD", 1.0)
    text = "\n".join(trace.summary_lines(_settings()))
    assert "item durations: none observed" in text
    assert "start (MISSION mode)  not observed (placeholder 5 s)" in text


def test_mark_start_once_and_finite() -> None:
    trace = MissionTrace()
    with pytest.raises(ValueError):
        trace.mark_start(float("nan"))
    trace.mark_start(1.0)
    with pytest.raises(RuntimeError):
        trace.mark_start(2.0)


def test_monitor_status_logged_on_change_only() -> None:
    trace = MissionTrace()
    trace.mark_start(0.0)
    waiting = MissionStatus(MissionState.WAITING_FOR_START, detail="start requested")
    for now in (0.1, 0.2, 0.3):
        trace.monitor_status(waiting, now)
    trace.monitor_status(MissionStatus(MissionState.ENDED, EndReason.MODE_CHANGED), 0.4)
    monitor_events = [e.text for e in trace.events if e.source == "monitor"]
    assert monitor_events == ["waiting_for_start start requested", "ended mode_changed"]


def test_combiner_observer_sees_only_accepted_updates() -> None:
    trace = MissionTrace()
    combiner = MissionTelemetryCombiner(observer=trace.observe)
    combiner.update_flight_mode("MISSION", 2.0)
    combiner.update_flight_mode("HOLD", 1.0)  # out of order: dropped by the combiner
    assert [e.text for e in trace.events] == ["MISSION"]


def test_failing_observer_never_stops_telemetry() -> None:
    def broken(stream, value, now_s):
        raise RuntimeError("trace bug")

    combiner = MissionTelemetryCombiner(observer=broken)
    combiner.update_flight_mode("MISSION", 1.0)
    combiner.update_flight_mode("HOLD", 2.0)
    for update in (combiner.update_armed, combiner.update_in_air):
        update(True, 2.0)
    combiner.update_progress(1, 3, 2.0)
    sample = combiner.sample()
    assert sample is not None and sample.flight_mode == "HOLD"
    assert combiner.observer_error == "RuntimeError: trace bug"


def test_failing_status_observer_does_not_change_monitor_result() -> None:
    def broken(status, now):
        raise RuntimeError("trace bug")

    async def no_sleep(_):
        return None

    def run(on_status):
        clock = iter(float(n) for n in range(100))
        monitor = MissionExecutionMonitor(_settings())
        monitor.start(0.0)
        return asyncio.run(
            run_monitor(
                monitor,
                MissionTelemetryCombiner(),
                0.0,
                lambda: next(clock),
                0.1,
                sleep=no_sleep,
                on_status=on_status,
            )
        )

    assert run(broken) == run(None)
    assert run(broken).is_terminal


def test_fake_flight_prints_trace_and_keeps_commands_unchanged(capsys) -> None:
    vehicle = FakeVehicle()
    result = _fly(vehicle)
    out = capsys.readouterr().out
    assert result.passed
    assert vehicle.commands == ["arm", "start_mission", "return_to_launch"]  # trace sends nothing
    assert "flight_mode: MISSION" in out and "flight_mode: RETURN_TO_LAUNCH" in out
    assert "monitor: completed" in out
    assert result.trace_lines and result.trace_lines[0].startswith("Mission trace")
    assert "Mission trace" in out


def test_fake_flight_prints_trace_even_when_preflight_refuses_before_arm(capsys) -> None:
    vehicle = FakeVehicle()
    original_upload = vehicle.mission.upload_mission

    async def upload_then_someone_arms(plan):
        await original_upload(plan)
        vehicle.armed = True

    vehicle.mission.upload_mission = upload_then_someone_arms
    with pytest.raises(Exception, match="already armed"):
        _fly(vehicle)
    out = capsys.readouterr().out
    assert "Mission trace" in out and "not observed" in out
    assert vehicle.commands == []


def test_fake_flight_trace_can_be_silenced() -> None:
    vehicle = FakeVehicle()
    result = asyncio.run(
        fly_waypoint_mission(
            vehicle,
            SQUARE,
            LIMITS,
            MISSION_MODULE,
            health_timeout_s=1.0,
            settings_for=lambda n: settings(expected_item_count=n),
            check_interval_s=0.01,
            return_settings=FAST_RETURN,
            emit=None,
        )
    )
    assert result.passed and result.trace_lines
