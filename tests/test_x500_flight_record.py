"""Tests for the SITL flight script's JSON run record.

Fake vehicle, fake clocks and fake git only. Nothing here shows that PX4 SITL
ran; it checks what the record says about runs the fake vehicle produced.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from simulation.mavsdk import flight_record
from simulation.mavsdk.flight_record import Outcome, classify
from simulation.mavsdk.waypoint_mission_flight import fly_waypoint_mission, main
from tests.test_x500_mission_telemetry import (
    FAST_RETURN,
    MISSION_MODULE,
    FakeVehicle,
    Mode,
    settings,
)
from x500.flight.preflight import PreflightRefused
from x500.flight.px4_limits import Px4LimitsRefused
from x500.flight.waypoint_mission import MissionCheckError

SQUARE_FILE = Path(__file__).resolve().parents[1] / "simulation/mavsdk/x500_waypoint_square.json"
FAKE_REVISION = {"commit": "abc1234", "tracked_changes": False, "error": None}


def fake_now():
    times = iter(
        datetime(2026, 11, 12, 18, 0, 0, tzinfo=UTC) + timedelta(seconds=s)
        for s in range(0, 1000, 42)
    )
    return lambda: next(times)


def fake_flight(vehicle):
    """Stand-in for run_flight: fly the fake vehicle with fast test budgets."""

    async def flight(config, waypoints, limits, settings_for, emit=print):
        config.validate()
        return await fly_waypoint_mission(
            vehicle,
            waypoints,
            limits,
            MISSION_MODULE,
            health_timeout_s=1.0,
            settings_for=lambda n: settings(expected_item_count=n),
            check_interval_s=0.01,
            return_settings=FAST_RETURN,
            emit=emit,
        )

    return flight


def run_main(tmp_path, vehicle=None, extra=(), flight=None):
    argv = ["--record-dir", str(tmp_path / "runs"), *extra]
    main(
        argv,
        flight=flight or fake_flight(vehicle),
        revision=lambda: FAKE_REVISION,
        now=fake_now(),
    )


def only_record(tmp_path) -> dict:
    files = sorted((tmp_path / "runs").glob("*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_nominal_fake_run_writes_pass_record(tmp_path, capsys) -> None:
    vehicle = FakeVehicle()
    run_main(tmp_path, vehicle, extra=["--label", "A0"])
    record = only_record(tmp_path)
    assert record["schema"] == flight_record.SCHEMA
    assert record["outcome"] == "pass" and record["error"] is None
    assert record["label"] == "A0" and record["argv"][-2:] == ["--label", "A0"]
    assert record["code"] == FAKE_REVISION
    assert record["duration_s"] == 42.0
    assert record["mission"]["sha256"] == flight_record.file_sha256(SQUARE_FILE)
    assert len(record["mission"]["waypoints"]) == 5
    assert record["monitor_status"]["state"] == "completed"
    assert record["rtl_requested"] is True
    assert record["return_status"]["state"] == "landed"
    # PX4 values read by the limit check, as the fake vehicle reported them.
    assert record["px4_limit_params_read"]["GF_MAX_VER_DIST"] == 40.0
    assert record["px4_limit_params_read"]["RTL_RETURN_ALT"] == 20.0
    # X500 SITL placeholders in use (not the fast test budgets the fake flew).
    assert record["companion_settings"]["monitor"]["max_item_time_s"] == 60.0
    assert record["companion_settings"]["mission_limits"]["max_relative_altitude_m"] == 30.0
    assert any(line.startswith("Monitor: completed") for line in record["lines"])
    assert any(line.startswith("Mission trace") for line in record["lines"])
    assert "ULog file name and sha256" in record["not_captured"]
    name = next((tmp_path / "runs").glob("*.json")).name
    assert name == "x500-flight-20261112T180000Z-A0-pass.json"
    out = capsys.readouterr().out
    assert "PASS: simulated waypoint mission" in out and "Run record written" in out
    assert vehicle.commands == ["arm", "start_mission", "return_to_launch"]


def test_px4_limit_refusal_is_recorded_with_values_and_still_raised(tmp_path) -> None:
    vehicle = FakeVehicle()
    vehicle.params["RTL_RETURN_ALT"] = 60.0  # PX4 default, above the 40 m SITL fence
    with pytest.raises(Px4LimitsRefused):
        run_main(tmp_path, vehicle)
    record = only_record(tmp_path)
    assert record["outcome"] == "refused_px4_limits"
    assert record["px4_limit_params_read"]["RTL_RETURN_ALT"] == 60.0
    assert any("RTL_RETURN_ALT 60 m is above" in r for r in record["error"]["reasons"])
    assert record["monitor_status"] is None and record["rtl_requested"] is None
    assert vehicle.commands == [] and vehicle.plan is None


def test_preflight_refusal_is_recorded(tmp_path) -> None:
    vehicle = FakeVehicle()
    vehicle.armed, vehicle.in_air, vehicle.mode = True, True, Mode.MISSION
    with pytest.raises(PreflightRefused):
        run_main(tmp_path, vehicle)
    record = only_record(tmp_path)
    assert record["outcome"] == "refused_preflight"
    assert record["px4_limit_params_read"] == {}  # refused before the limit check
    assert vehicle.commands == []


def test_stalled_fake_run_is_recorded_as_fail(tmp_path) -> None:
    vehicle = FakeVehicle(stall=True)

    async def flight(config, waypoints, limits, settings_for, emit=print):
        return await fly_waypoint_mission(
            vehicle,
            waypoints,
            limits,
            MISSION_MODULE,
            health_timeout_s=1.0,
            settings_for=lambda n: settings(expected_item_count=n, max_item_time_s=0.2),
            check_interval_s=0.01,
            return_settings=FAST_RETURN,
            emit=emit,
        )

    with pytest.raises(SystemExit, match="FAIL"):
        run_main(tmp_path, flight=flight)
    record = only_record(tmp_path)
    assert record["outcome"] == "fail"
    assert record["monitor_status"]["reason"] == "item_stalled"
    assert record["monitor_status"]["recommendation"] == "return_to_launch"


def test_ctrl_c_is_recorded_and_propagates(tmp_path) -> None:
    async def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_main(tmp_path, flight=interrupted)
    assert only_record(tmp_path)["outcome"] == "interrupted"


def test_failed_record_write_does_not_hide_the_refusal(tmp_path, monkeypatch, capsys) -> None:
    def broken(record, directory):
        raise OSError("disk full")

    monkeypatch.setattr(flight_record, "write_record", broken)
    vehicle = FakeVehicle()
    vehicle.armed = True
    with pytest.raises(PreflightRefused):
        run_main(tmp_path, vehicle)
    assert "WARNING: run record not written (OSError: disk full)" in capsys.readouterr().out


def _must_not_fly(*args, **kwargs):
    raise AssertionError("flight must not start")


@pytest.mark.parametrize(
    "extra, match",
    [
        (["--label", "../A1"], "Run label"),
        (["--label", ""], "Run label"),
        (["--label", "x" * 33], "Run label"),
    ],
)
def test_bad_label_refused_before_flight(tmp_path, extra, match) -> None:
    with pytest.raises(SystemExit, match=match):
        run_main(tmp_path, extra=extra, flight=_must_not_fly)
    assert not (tmp_path / "runs").exists()


def test_label_without_record_dir_refused_before_flight() -> None:
    with pytest.raises(SystemExit, match="--label needs --record-dir"):
        main(["--label", "A1"], flight=_must_not_fly)


def test_record_dir_that_is_a_file_refused_before_flight(tmp_path) -> None:
    target = tmp_path / "runs"
    target.write_text("not a directory", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        run_main(tmp_path, flight=_must_not_fly)


def test_without_record_dir_nothing_is_written(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        flight_record, "write_record", lambda *a: pytest.fail("no record requested")
    )
    main([], flight=fake_flight(FakeVehicle()), revision=lambda: FAKE_REVISION, now=fake_now())


def test_write_record_never_overwrites(tmp_path) -> None:
    record = {"started_utc": "2026-11-12T18:00:00+00:00", "label": None, "outcome": "fail"}
    first = flight_record.write_record(record, tmp_path)
    second = flight_record.write_record(record, tmp_path)
    assert first.name == "x500-flight-20261112T180000Z-run-fail.json"
    assert second.name == "x500-flight-20261112T180000Z-run-fail-2.json"
    assert json.loads(first.read_text(encoding="utf-8")) == record


def test_non_finite_values_become_strings_so_json_stays_valid() -> None:
    record = flight_record._jsonable({"a": float("nan"), "b": (1, float("inf")), "c": Mode.HOLD})
    assert record == {"a": "nan", "b": [1, "inf"], "c": 1}
    json.dumps(record, allow_nan=False)


def _result(passed=False, fault_ok=False):
    return SimpleNamespace(passed=passed, injected_fault_path_ok=fault_ok)


@pytest.mark.parametrize(
    "result, injecting, error, expected",
    [
        (_result(passed=True), False, None, Outcome.PASS),
        (_result(), False, None, Outcome.FAIL),
        # An injected run can never be a PASS, even if the mission completed.
        (_result(passed=True), True, None, Outcome.INJECTED_FAULT_PATH_FAIL),
        (_result(fault_ok=True), True, None, Outcome.INJECTED_FAULT_PATH_OK),
        (None, False, MissionCheckError(["too far"]), Outcome.REFUSED_MISSION_CHECK),
        (None, False, PreflightRefused(("armed",)), Outcome.REFUSED_PREFLIGHT),
        (None, False, Px4LimitsRefused(("fence",)), Outcome.REFUSED_PX4_LIMITS),
        (None, False, TimeoutError("no home"), Outcome.ERROR),
        (None, False, None, Outcome.ERROR),
    ],
)
def test_classify_matches_script_verdicts(result, injecting, error, expected) -> None:
    assert classify(result, injecting, error) is expected


def test_code_revision_reports_commit_and_tracked_changes() -> None:
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd[3:])
        out = "deadbeef\n" if cmd[3] == "rev-parse" else " M x500/flight/settings.py\n"
        return SimpleNamespace(stdout=out)

    revision = flight_record.code_revision(Path("/repo"), run=run)
    assert revision == {"commit": "deadbeef", "tracked_changes": True, "error": None}
    assert calls[1] == ["status", "--porcelain", "--untracked-files=no"]


def test_code_revision_never_raises_without_git() -> None:
    def run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd)

    revision = flight_record.code_revision(Path("/not-a-repo"), run=run)
    assert revision["commit"] is None and "CalledProcessError" in revision["error"]


def test_real_checkout_revision_is_readable() -> None:
    # Runs real git on this checkout; skipped where git is unavailable.
    revision = flight_record.code_revision()
    if revision["error"]:
        pytest.skip(revision["error"])
    assert len(revision["commit"]) >= 40
