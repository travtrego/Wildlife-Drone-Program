"""PX4 SITL waypoint mission flight with execution monitoring (X500 flight layer).

Simulation only. Refuses any vehicle endpoint other than the loopback SITL
listener (same guard as the smoke mission). Sequence:

1. Check the waypoint file against the X500 advisory limits (model inputs).
2. Connect, wait for position/home health, read PX4 home.
3. Preflight gate (``require_preflight_ready``): refuse, sending nothing, unless
   fresh telemetry shows a disarmed vehicle on the ground, battery at or above
   the companion minimum and every PX4 health flag, including ``is_armable``,
   True. This keeps the script from replacing a mission on a vehicle that is
   already armed or flying.
3a. PX4 limit check (``require_px4_limits_consistent``): read ``GF_MAX_HOR_DIST``,
   ``GF_MAX_VER_DIST``, ``GF_ACTION``, ``MPC_XY_VEL_MAX``, ``BAT_LOW_THR`` and
   ``RTL_RETURN_ALT`` (read-only) and refuse, sending nothing, if the companion
   limits are looser than PX4's, a PX4 geofence limit is disabled (0),
   ``GF_ACTION`` is not Hold/Return/Land, PX4's RTL altitude is above its
   vertical geofence, or a value cannot be read.
4. Start read-only telemetry subscriptions, upload the mission and verify it by
   read-back (``upload_and_verify``).
5. Re-run the preflight gate, then arm (PX4 arming checks stay enabled) and
   request ``start_mission``.
6. Run :class:`MissionExecutionMonitor` on the combined telemetry until it ends.
   A read-only :class:`MissionTrace` prints every mode/armed/in-air/progress
   and monitor change as it happens and a summary (stream rates, item times,
   margins against the timing placeholders) when the script exits.
7. Request ``RETURN_TO_LAUNCH`` only if :func:`follow_up_request` allows it
   (mission completed, or the monitor recommended RTL, with fresh telemetry
   still showing an armed, airborne vehicle in MISSION/HOLD). Any other outcome
   sends nothing: PX4 or the pilot owns the vehicle.
8. After an RTL request, :class:`ReturnLandingMonitor` watches the same
   telemetry (read-only) until PX4 reports RTL/LAND, lands and disarms, or the
   watch ends (request not accepted, pilot takeover, PX4 left RTL/LAND, landed
   but not disarmed, timeout, stale telemetry). It sends nothing further in
   any case: no retry, no LAND, no disarm.

PASS means the monitor saw the mission complete and, after the RTL request,
the return watch saw PX4 enter RTL/LAND, land and disarm, in simulation.

SITL fault injection (optional): ``--inject-item-budget-s`` and
``--inject-mission-budget-s`` replace the monitor's item/mission time
placeholders with *shorter* values (longer values are refused), so a normal
simulated mission ends ``ITEM_STALLED`` or ``MISSION_TIMEOUT``. That is the
only path on which this script sends a command because of a monitor fault (the
proposed RTL), and it could not be exercised in SITL without editing code.
Such a run never prints PASS: it prints ``INJECTED FAULT PATH OK`` only when the
monitor ended ITEM_STALLED or MISSION_TIMEOUT, RTL was requested and the watch
saw RTL/LAND, landing and disarm. Nothing is changed in PX4. One
nominal PX4 SITL pass (before the return watch existed) is recorded in
docs/SITL_VALIDATION_2026-11-01.md; failure paths and the return watch are
unit-tested only.

Run record (optional): ``--record-dir DIR`` writes one JSON file per run
(:mod:`simulation.mavsdk.flight_record`) with the code revision, mission file
checksum, companion settings in use, the PX4 limit parameters read, the
monitor/return results, every trace line and the script's verdict, including
refusals, errors and Ctrl+C. ``--label`` tags it with a checklist row. The
record adds nothing on the vehicle side and does not capture PX4/Gazebo
versions, the ULog or the PX4 console.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.autonomy.sitl import SitlMissionConfig, load_sitl_config
from simulation.mavsdk import flight_record
from simulation.mavsdk.smoke_mission import (
    _wait_for_connection,
    _wait_for_health,
)
from simulation.mavsdk.waypoint_upload_check import _read_home, load_waypoints
from x500.flight.mission_monitor import (
    EndReason,
    MissionExecutionMonitor,
    MissionState,
    MissionStatus,
    MonitorSettings,
    Recommendation,
    tighten_time_budgets,
)
from x500.flight.mission_telemetry import (
    MissionTelemetryCombiner,
    follow_up_request,
    run_monitor,
    subscribe_mission_telemetry,
)
from x500.flight.mission_trace import MissionTrace
from x500.flight.monitor_settings import (
    X500_SITL_RETURN_SETTINGS,
    x500_sitl_monitor_settings,
)
from x500.flight.preflight import PreflightLimits, require_preflight_ready
from x500.flight.px4_limits import require_px4_limits_consistent
from x500.flight.return_monitor import ReturnLandingMonitor, ReturnSettings, ReturnStatus
from x500.flight.settings import X500_SITL_MISSION_LIMITS, X500_SITL_PREFLIGHT_LIMITS
from x500.flight.waypoint_mission import (
    LocalWaypoint,
    MissionCheckError,
    MultirotorMissionLimits,
    build_mission_items,
    check_mission,
    upload_and_verify,
)

# Placeholders for SITL development, not measured values.
CHECK_INTERVAL_S = 0.2


@dataclass(frozen=True)
class FlightResult:
    status: MissionStatus
    rtl_requested: bool
    follow_up_reason: str
    landed: bool
    stream_errors: dict
    trace_lines: tuple[str, ...] = ()
    # Return watch result after an RTL request; None when no RTL was requested.
    return_status: ReturnStatus | None = None
    # PX4 limit parameters read before upload (read-only), for run records.
    px4_limit_values: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status.state is MissionState.COMPLETED and self.rtl_requested and self.landed

    @property
    def injected_fault_path_ok(self) -> bool:
        """True when a time-budget fault ended the mission and the RTL path completed.

        Used only for ``--inject-*`` SITL runs; it is never a mission PASS.
        """

        return (
            self.status.reason in (EndReason.ITEM_STALLED, EndReason.MISSION_TIMEOUT)
            and self.status.recommendation is Recommendation.RETURN_TO_LAUNCH
            and self.rtl_requested
            and self.landed
        )


async def fly_waypoint_mission(
    drone: Any,
    waypoints: list[LocalWaypoint],
    limits: MultirotorMissionLimits,
    mission_module: Any,
    health_timeout_s: float,
    settings_for: Callable[[int], MonitorSettings] = x500_sitl_monitor_settings,
    clock: Callable[[], float] = time.monotonic,
    check_interval_s: float = CHECK_INTERVAL_S,
    return_settings: ReturnSettings = X500_SITL_RETURN_SETTINGS,
    preflight_limits: PreflightLimits = X500_SITL_PREFLIGHT_LIMITS,
    emit: Callable[[str], None] | None = print,
) -> FlightResult:
    """Fly one verified mission on an already connected *simulated* vehicle.

    Raises :class:`PreflightRefused` before upload, or before arm, if the
    vehicle is not ready, and :class:`Px4LimitsRefused` before upload if the
    companion limits contradict the PX4 parameters; nothing is sent in either case.
    """

    # Status lines go through ``emit`` so a run record can keep them; with no
    # emitter they are printed as before (the trace stays silent).
    say = emit if emit is not None else print
    await _wait_for_health(drone, health_timeout_s)
    home = await _read_home(drone, health_timeout_s)
    await require_preflight_ready(drone, preflight_limits, health_timeout_s, clock)
    px4_report = await require_px4_limits_consistent(
        drone, limits, preflight_limits, health_timeout_s
    )
    items = build_mission_items(waypoints, home, limits)
    settings = settings_for(len(items))
    monitor = MissionExecutionMonitor(settings)

    # Read-only trace: prints each mode/armed/in-air/progress/monitor change and
    # summarizes stream rates, item times and placeholder margins at the end.
    trace = MissionTrace(emit=emit)
    combiner = MissionTelemetryCombiner(observer=trace.observe)
    tasks = subscribe_mission_telemetry(drone, combiner, clock)
    trace_lines: tuple[str, ...] = ()
    try:
        await upload_and_verify(drone, items, home, mission_module)
        # Upload/read-back takes time; check again immediately before arming.
        await require_preflight_ready(drone, preflight_limits, health_timeout_s, clock)
        say(f"Mission of {len(items)} items verified; arming (PX4 checks enabled) ...")
        await drone.action.arm()
        await drone.mission.start_mission()
        started_at = clock()
        monitor.start(started_at)
        trace.mark_start(started_at)
        say("Mission start requested; monitoring ...")
        status = await run_monitor(
            monitor, combiner, started_at, clock, check_interval_s, on_status=trace.monitor_status
        )
        reason = status.reason.value if status.reason else ""
        say(
            f"Monitor: {status.state.value} {reason} {status.detail} "
            f"(item {status.current_item}/{status.total_items})"
        )

        follow = follow_up_request(status, combiner.sample(), clock(), settings.max_telemetry_age_s)
        landed = False
        return_status: ReturnStatus | None = None
        if follow.request_return_to_launch:
            say("Requesting PX4 RETURN_TO_LAUNCH ...")
            await drone.action.return_to_launch()
            requested_at = clock()
            watch = ReturnLandingMonitor(return_settings)
            watch.start(requested_at)
            return_status = await run_monitor(
                watch,
                combiner,
                requested_at,
                clock,
                check_interval_s,
                on_status=trace.monitor_status,
            )
            landed = return_status.landed_and_disarmed
            reason = return_status.reason.value if return_status.reason else ""
            # Read-only result; nothing further is sent whatever it says.
            say(f"Return watch: {return_status.state.value} {reason} {return_status.detail}")
        else:
            say(f"No follow-up command: {follow.reason}")
        trace_lines = tuple(trace.summary_lines(settings))
        return FlightResult(
            status=status,
            rtl_requested=follow.request_return_to_launch,
            follow_up_reason=follow.reason,
            landed=landed,
            return_status=return_status,
            stream_errors={s.value: d for s, d in combiner.stream_errors.items()},
            trace_lines=trace_lines,
            px4_limit_values=dict(px4_report.values),
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if emit is not None:
            # Printed on every exit, including refusals and exceptions after
            # subscription, so a failed run still shows what was received.
            for line in trace_lines or trace.summary_lines(settings):
                emit(line)
            if combiner.observer_error:
                emit(f"Trace stopped early: {combiner.observer_error}")


def fault_injected_settings_for(
    base: Callable[[int], MonitorSettings] = x500_sitl_monitor_settings,
    max_item_time_s: float | None = None,
    max_mission_time_s: float | None = None,
) -> Callable[[int], MonitorSettings]:
    """Return a ``settings_for`` that tightens ``base``'s time budgets (SITL only).

    Checked once here with a one-item mission so a loosening or invalid value is
    refused before connecting; :func:`tighten_time_budgets` checks again for the
    real item count.
    """

    if max_item_time_s is None and max_mission_time_s is None:
        return base
    tighten_time_budgets(
        base(1), max_item_time_s=max_item_time_s, max_mission_time_s=max_mission_time_s
    )

    def settings_for(expected_item_count: int) -> MonitorSettings:
        return tighten_time_budgets(
            base(expected_item_count),
            max_item_time_s=max_item_time_s,
            max_mission_time_s=max_mission_time_s,
        )

    return settings_for


async def run_flight(
    config: SitlMissionConfig,
    waypoints: list[LocalWaypoint],
    limits: MultirotorMissionLimits,
    settings_for: Callable[[int], MonitorSettings] = x500_sitl_monitor_settings,
    emit: Callable[[str], None] | None = print,
) -> FlightResult:
    config.validate()  # refuses non-loopback, wildcard and serial endpoints
    reasons = check_mission(waypoints, limits)
    if reasons:
        raise MissionCheckError(reasons)
    # Import here so unit tests do not require MAVSDK to be installed.
    from mavsdk import System
    from mavsdk import mission as mavsdk_mission

    drone = System()
    (emit or print)(f"Connecting to PX4 SITL at {config.system_address} ...")
    await drone.connect(system_address=config.system_address)
    await _wait_for_connection(drone, config.connection_timeout_s)
    return await fly_waypoint_mission(
        drone,
        waypoints,
        limits,
        mavsdk_mission,
        config.health_timeout_s,
        settings_for,
        emit=emit,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description="X500 SITL monitored waypoint mission")
    parser.add_argument("--config", type=Path, default=here / "sitl_config.json")
    parser.add_argument("--mission", type=Path, default=here / "x500_waypoint_square.json")
    parser.add_argument(
        "--inject-item-budget-s",
        type=float,
        default=None,
        help="SITL fault injection: shorter per-item budget (s) to force ITEM_STALLED",
    )
    parser.add_argument(
        "--inject-mission-budget-s",
        type=float,
        default=None,
        help="SITL fault injection: shorter whole-mission budget (s) to force MISSION_TIMEOUT",
    )
    parser.add_argument(
        "--record-dir",
        type=Path,
        default=None,
        help="write a JSON run record here (e.g. sitl_runs/, ignored by Git)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="run label for the record file name, e.g. a checklist row such as A3",
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    flight: Callable[..., Any] = run_flight,
    revision: Callable[[], dict] = flight_record.code_revision,
    now: Callable[[], Any] = flight_record.utc_now,
) -> None:
    """Entry point. ``flight``, ``revision`` and ``now`` are seams for unit tests."""

    args = parse_args(argv)
    record_dir = None
    label = None
    try:
        if args.label is not None:
            if args.record_dir is None:
                raise ValueError("--label needs --record-dir")
            label = flight_record.validate_label(args.label)
        if args.record_dir is not None:
            record_dir = flight_record.prepare_record_dir(args.record_dir)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Refused run-record option: {exc}") from exc
    config = load_sitl_config(args.config)
    waypoints = load_waypoints(args.mission)
    injecting = args.inject_item_budget_s is not None or args.inject_mission_budget_s is not None
    try:
        settings_for = fault_injected_settings_for(
            x500_sitl_monitor_settings, args.inject_item_budget_s, args.inject_mission_budget_s
        )
    except ValueError as exc:
        raise SystemExit(f"Refused fault-injection budget: {exc}") from exc

    lines: list[str] = []

    def emit(line: str) -> None:
        print(line)
        lines.append(line)

    if injecting:
        injected = settings_for(len(waypoints))
        emit(
            "SITL FAULT INJECTION: monitor budgets item "
            f"{injected.max_item_time_s:g} s, mission {injected.max_mission_time_s:g} s "
            "(shortened placeholders). Expected: item_stalled or mission_timeout, "
            "RTL requested, return watch landed. This run cannot PASS."
        )
    started_utc = now()
    result: FlightResult | None = None
    error: BaseException | None = None
    try:
        result = asyncio.run(
            flight(config, waypoints, X500_SITL_MISSION_LIMITS, settings_for, emit=emit)
        )
    except (Exception, KeyboardInterrupt) as exc:
        error = exc
        raise
    finally:
        if record_dir is not None:
            _write_run_record(
                record_dir,
                label=label,
                argv=sys.argv[1:] if argv is None else argv,
                revision=revision(),
                started_utc=started_utc,
                ended_utc=now(),
                config=config,
                mission_path=args.mission,
                waypoints=waypoints,
                settings_for=settings_for,
                injecting=injecting,
                result=result,
                error=error,
                lines=lines,
            )
    if result.stream_errors:
        print(f"Telemetry stream problems: {result.stream_errors}")
    if injecting:
        if not result.injected_fault_path_ok:
            raise SystemExit(
                "FAIL: injected time-budget fault did not end with the monitor's RTL "
                "proposal, an RTL request, landing and disarm."
            )
        print(
            "INJECTED FAULT PATH OK: monitor ended "
            f"{result.status.reason.value}, RTL requested, landed and disarmed (not a PASS)."
        )
        return
    if not result.passed:
        raise SystemExit(
            "FAIL: monitored SITL waypoint mission did not complete, return, land and disarm."
        )
    print("PASS: simulated waypoint mission completed, RTL requested, landed and disarmed.")


def _write_run_record(
    record_dir: Path,
    *,
    mission_path: Path,
    waypoints: list[LocalWaypoint],
    settings_for: Callable[[int], MonitorSettings],
    **fields: Any,
) -> None:
    """Write the run record; a failure to write is reported, never raised.

    Runs in ``finally`` so a refusal, error or Ctrl+C is still recorded, and
    must not hide the exception that ended the run.
    """

    try:
        # One mission item per waypoint (build_mission_items); an empty mission
        # is refused before this and has no monitor settings to record.
        monitor_settings = settings_for(len(waypoints))
    except ValueError:
        monitor_settings = None
    try:
        record = flight_record.build_record(
            mission_path=mission_path,
            mission_sha256=flight_record.file_sha256(mission_path),
            waypoints=waypoints,
            mission_limits=X500_SITL_MISSION_LIMITS,
            preflight_limits=X500_SITL_PREFLIGHT_LIMITS,
            monitor_settings=monitor_settings,
            return_settings=X500_SITL_RETURN_SETTINGS,
            **fields,
        )
        path = flight_record.write_record(record, record_dir)
    except Exception as exc:  # disk full, permissions, unserializable value
        print(f"WARNING: run record not written ({type(exc).__name__}: {exc})")
        return
    print(f"Run record written: {path} (outcome {record['outcome']})")


if __name__ == "__main__":
    main()
