# X500 multirotor flight layer

Waypoint-autonomy code exercised first on the X500 (owner decision 2026-10-21: no Jetson, perception or AI logic on the X500). Code is aircraft-agnostic; per-aircraft numbers are passed in as settings so Coyote can reuse it. It stays here, not in `shared/`, until it has SITL evidence (shared-code rule in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md)).

## `mission_monitor.py`

Deterministic classifier for a waypoint mission that PX4 is already flying. It never commands the vehicle. Feed it timestamped samples of flight mode, armed, in-air and MAVSDK `mission_progress` (`current`, `total`); call `check(now)` periodically so silence is detected.

| Outcome | Trigger | Recommendation |
|---|---|---|
| `COMPLETED` | Final item reached (`current == total`) in `MISSION`/`HOLD`, armed, after observed airborne state | none |
| `PILOT_TAKEOVER` | Any pilot mode | none — companion yields |
| `PX4_RECOVERY_MODE` | `RETURN_TO_LAUNCH` or `LAND` (commanded or failsafe) | none — never fight PX4 |
| `MODE_CHANGED` | Any other mode before completion (e.g. `HOLD`, `OFFBOARD`). Exception: `HOLD` while airborne on the last item (`current == total - 1`) waits up to `completion_grace_s` (X500 SITL placeholder 3 s) for progress to report completion, because PX4 SITL switched to HOLD before final-item progress on 2026-11-01 | none |
| `DISARMED` / `LANDED_EARLY` / `NEVER_AIRBORNE` | Vehicle state inconsistent with an incomplete mission | none |
| `MISSION_CHANGED` / `PROGRESS_REGRESSED` | Item total differs from the uploaded count, item index beyond total, or index goes backwards | none |
| `START_TIMEOUT` | Armed `MISSION` mode not reported within the start budget | none |
| `TELEMETRY_STALE` | No valid sample within the age limit (malformed samples do not count) | none — PX4 link-loss failsafe owns the aircraft |
| `ITEM_STALLED` / `MISSION_TIMEOUT` | Still in `MISSION` but an item or the whole mission exceeds its time budget | *proposes* `RETURN_TO_LAUNCH`; caller decides, PX4 flies it |

Terminal outcomes are sticky; create a new monitor per attempt. X500 timing values in [`monitor_settings.py`](monitor_settings.py) (10 s start, 60 s per item, 300 s mission, 2 s telemetry age) are **model inputs / SITL development placeholders**, not measurements or PX4 parameters.

**Evidence status:** unit-tested only (`tests/test_x500_mission_monitor.py`); mode names checked against MAVSDK-Python 3.17.2 `FlightMode` without a vehicle. One nominal SITL run reached `COMPLETED` at item 5/5 ([SITL record 2026-11-01](../../docs/SITL_VALIDATION_2026-11-01.md)). The specific modes reported during takeoff and after the last item, and the `mission_progress` values at start, were not printed and remain unobserved. No hardware, bench or flight evidence.

## `preflight.py`

Companion-side readiness gate run by both SITL mission scripts before upload, and by the flight script again immediately before arm. It reads one value each of armed, in-air, battery and health (read-only) and refuses, sending nothing, unless the vehicle is **disarmed and on the ground**, battery is at or above the companion minimum, and every PX4 health flag (gyro/accel/mag calibration, local/global/home position, `is_armable`) is True. Missing, malformed or non-boolean readings refuse; all reasons are reported together. This stops the scripts from replacing a mission on a vehicle that is already armed or flying. It only withholds requests: PX4 arming checks stay enabled and authoritative, and passing the gate does not make PX4 arm.

X500 values in [`settings.py`](settings.py) (40 % battery, set by the owner on 2026-10-31; 2 s telemetry age) are **model inputs / SITL development placeholders**; the battery figure is not a reserve calculation and must stay at or above the PX4 battery failsafe thresholds.

**Evidence status:** unit-tested only (`tests/test_x500_preflight.py`, plus gate cases in `tests/test_x500_mission_telemetry.py`). MAVSDK-Python 3.17.2 `Health`/`Battery` field names and the 0-100 `remaining_percent` scale were checked against the installed package without a vehicle. In one SITL run it passed in both scripts and before arm, so PX4 SITL reported every flag True and battery ≥ 40 % once home was valid ([SITL record 2026-11-01](../../docs/SITL_VALIDATION_2026-11-01.md)). Refusal paths are unit-tested only.

## `px4_limits.py`

Read-only check, run by the flight script after the first preflight gate and before upload, that the companion limits sit inside the PX4 parameters they rely on. It reads `GF_MAX_HOR_DIST`, `GF_MAX_VER_DIST`, `GF_ACTION`, `MPC_XY_VEL_MAX` and `BAT_LOW_THR` once and refuses, sending nothing, if the companion distance-from-home or ceiling is above an *enabled* PX4 geofence limit, the companion max speed is above `MPC_XY_VEL_MAX`, the companion battery minimum is below `BAT_LOW_THR`, or any value is unreadable, missing, non-numeric or out of range. Equal values pass. A disabled PX4 geofence limit (`0`, the PX4 default) also refuses, and so does any `GF_ACTION` other than Hold (2), Return (3) or Land (5) (owner decision 2026-11-06: no PX4 backstop, no mission). Terminate (4) refuses too; whether it is acceptable on a real aircraft is not decided. The SITL session checklist sets a simulator geofence before each run. The check never sets a parameter, and passing it does not mean PX4 is tuned for an aircraft, only that the companion limits do not contradict it.

**Evidence status:** unit-tested only (`tests/test_x500_px4_limits.py`, plus refusal cases in `tests/test_x500_mission_telemetry.py`). Parameter names and units come from PX4 documentation and were **not** checked against the SITL PX4 build (`6041c961`); a renamed parameter makes the check refuse. Not yet run in PX4 SITL.

## `mission_trace.py`

Read-only record of what the companion received during a monitored mission, added because the 2026-11-01 SITL runs printed only the final monitor result: the modes reported during takeoff and after the last item, the `mission_progress` values at start, per-item times and stream rates were never observed, and the final-HOLD race was diagnosed from PX4's console instead of the script. `MissionTrace` prints one line for every change in flight mode, armed, in-air, mission progress and monitor state, timed relative to the `start_mission` request (`pre-start` before it). On exit, including refusals and exceptions after the telemetry subscription, it prints a summary with each stream's count, mean rate and largest gap; item durations (the item current at the start request is timed from the request, so takeoff counts toward it); time to `MISSION` mode, `in_air` and the final item; and the margin against each monitor placeholder in use (`EXCEEDS PLACEHOLDER` when an observation is larger). The trace never commands, never changes what the monitor sees and never decides pass/fail. A failing observer is disabled and reported (`Trace stopped early: ...`) instead of stopping telemetry. It is fed by an optional observer hook on `MissionTelemetryCombiner` and an optional `on_status` hook on `run_monitor`.

Its numbers are observations from one run, not validated limits; changing a placeholder from them is a separate, reviewed change. **Evidence status:** unit-tested only (`tests/test_x500_mission_trace.py`), with fake clocks and the in-memory fake vehicle. It has not run in PX4 SITL.

## `mission_telemetry.py`

Connects the monitor to MAVSDK. `MissionTelemetryCombiner` keeps the latest flight mode, armed, in-air and `mission_progress` values and builds one `MissionSample` stamped with the **oldest** of the periodic streams (mode, armed, in-air), so one silent stream makes the monitor report `TELEMETRY_STALE`. Mission progress is latched and required once but does not set the age, because MAVSDK may report it only when it changes. No sample is produced until every stream has reported; samples older than the start request are not fed; out-of-order updates are dropped. `subscribe_mission_telemetry` runs one read-only task per stream and records a stream that ends or fails. `run_monitor` feeds new samples and periodic checks until the monitor is terminal.

`follow_up_request` decides whether the ground script may *request* PX4 `RETURN_TO_LAUNCH` after the monitor ends: only after `COMPLETED` or a monitor RTL recommendation (`ITEM_STALLED`/`MISSION_TIMEOUT`), and only while fresh, valid telemetry still shows an armed, airborne vehicle in `MISSION`/`HOLD`. Pilot modes, PX4 `RETURN_TO_LAUNCH`/`LAND`, stale or invalid telemetry and every other end reason get no request.

[`simulation/mavsdk/waypoint_mission_flight.py`](../../simulation/mavsdk/waypoint_mission_flight.py) is the SITL entry point that uses it: loopback endpoint guard and waypoint-limit check before connecting, then health → home → preflight gate → PX4 limit check → upload/read-back → preflight gate → arm (PX4 arming checks stay enabled) → `start_mission` → monitor → RTL request if allowed → wait for landing. Run from the repository root with `gz_x500` SITL already running:

~~~bash
python -m simulation.mavsdk.waypoint_mission_flight
~~~

**Evidence status:** unit-tested only (`tests/test_x500_mission_telemetry.py`), with fake clocks and an in-memory fake vehicle. **One nominal SITL run passed** ([SITL record 2026-11-01](../../docs/SITL_VALIDATION_2026-11-01.md)): PX4 started the mission from the ground without a takeoff item, the monitor completed, RTL was requested and the vehicle landed. Still unobserved: the exact modes and stream rates (the run only shows they fit the current placeholders). Stall, takeover and stale-telemetry paths are unit-tested only. The 0.2 s check interval and 120 s landing timeout are SITL placeholders.
