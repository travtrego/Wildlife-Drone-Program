# X500 multirotor flight layer

Waypoint-autonomy code exercised first on the X500 (owner decision 2026-10-21: no Jetson, perception or AI logic on the X500). Code is aircraft-agnostic; per-aircraft numbers are passed in as settings so Coyote can reuse it. It stays here, not in `shared/`, until it has SITL evidence (shared-code rule in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md)).

## `mission_monitor.py`

Deterministic classifier for a waypoint mission that PX4 is already flying. It never commands the vehicle. Feed it timestamped samples of flight mode, armed, in-air and MAVSDK `mission_progress` (`current`, `total`); call `check(now)` periodically so silence is detected.

| Outcome | Trigger | Recommendation |
|---|---|---|
| `COMPLETED` | Final item reached (`current == total`) in `MISSION`/`HOLD`, armed, after observed airborne state | none |
| `PILOT_TAKEOVER` | Any pilot mode | none — companion yields |
| `PX4_RECOVERY_MODE` | `RETURN_TO_LAUNCH` or `LAND` (commanded or failsafe) | none — never fight PX4 |
| `MODE_CHANGED` | Any other mode before completion (e.g. `HOLD`, `OFFBOARD`) | none |
| `DISARMED` / `LANDED_EARLY` / `NEVER_AIRBORNE` | Vehicle state inconsistent with an incomplete mission | none |
| `MISSION_CHANGED` / `PROGRESS_REGRESSED` | Item total differs from the uploaded count, item index beyond total, or index goes backwards | none |
| `START_TIMEOUT` | Armed `MISSION` mode not reported within the start budget | none |
| `TELEMETRY_STALE` | No valid sample within the age limit (malformed samples do not count) | none — PX4 link-loss failsafe owns the aircraft |
| `ITEM_STALLED` / `MISSION_TIMEOUT` | Still in `MISSION` but an item or the whole mission exceeds its time budget | *proposes* `RETURN_TO_LAUNCH`; caller decides, PX4 flies it |

Terminal outcomes are sticky; create a new monitor per attempt. X500 timing values in [`monitor_settings.py`](monitor_settings.py) (10 s start, 60 s per item, 300 s mission, 2 s telemetry age) are **model inputs / SITL development placeholders**, not measurements or PX4 parameters.

**Evidence status:** unit-tested only (`tests/test_x500_mission_monitor.py`); mode names checked against MAVSDK-Python 3.17.2 `FlightMode` without a vehicle. **Not run against PX4 SITL.** Unobserved in SITL: which mode PX4/MAVSDK reports during the mission's takeoff and after the last item, and the exact `mission_progress` values at start and completion. No hardware, bench or flight evidence.

## `preflight.py`

Companion-side readiness gate run by both SITL mission scripts before upload, and by the flight script again immediately before arm. It reads one value each of armed, in-air, battery and health (read-only) and refuses, sending nothing, unless the vehicle is **disarmed and on the ground**, battery is at or above the companion minimum, and every PX4 health flag (gyro/accel/mag calibration, local/global/home position, `is_armable`) is True. Missing, malformed or non-boolean readings refuse; all reasons are reported together. This stops the scripts from replacing a mission on a vehicle that is already armed or flying. It only withholds requests: PX4 arming checks stay enabled and authoritative, and passing the gate does not make PX4 arm.

X500 values in [`settings.py`](settings.py) (40 % battery, set by the owner on 2026-10-31; 2 s telemetry age) are **model inputs / SITL development placeholders**; the battery figure is not a reserve calculation and must stay at or above the PX4 battery failsafe thresholds.

**Evidence status:** unit-tested only (`tests/test_x500_preflight.py`, plus gate cases in `tests/test_x500_mission_telemetry.py`). MAVSDK-Python 3.17.2 `Health`/`Battery` field names and the 0-100 `remaining_percent` scale were checked against the installed package without a vehicle. **Not run against PX4 SITL.** Unobserved: whether PX4 SITL reports `is_armable` True before the first arm request, and how the SITL battery simulator reports charge while disarmed.

## `mission_telemetry.py`

Connects the monitor to MAVSDK. `MissionTelemetryCombiner` keeps the latest flight mode, armed, in-air and `mission_progress` values and builds one `MissionSample` stamped with the **oldest** of the periodic streams (mode, armed, in-air), so one silent stream makes the monitor report `TELEMETRY_STALE`. Mission progress is latched and required once but does not set the age, because MAVSDK may report it only when it changes. No sample is produced until every stream has reported; samples older than the start request are not fed; out-of-order updates are dropped. `subscribe_mission_telemetry` runs one read-only task per stream and records a stream that ends or fails. `run_monitor` feeds new samples and periodic checks until the monitor is terminal.

`follow_up_request` decides whether the ground script may *request* PX4 `RETURN_TO_LAUNCH` after the monitor ends: only after `COMPLETED` or a monitor RTL recommendation (`ITEM_STALLED`/`MISSION_TIMEOUT`), and only while fresh, valid telemetry still shows an armed, airborne vehicle in `MISSION`/`HOLD`. Pilot modes, PX4 `RETURN_TO_LAUNCH`/`LAND`, stale or invalid telemetry and every other end reason get no request.

[`simulation/mavsdk/waypoint_mission_flight.py`](../../simulation/mavsdk/waypoint_mission_flight.py) is the SITL entry point that uses it: loopback endpoint guard and waypoint-limit check before connecting, then health → home → preflight gate → upload/read-back → preflight gate → arm (PX4 arming checks stay enabled) → `start_mission` → monitor → RTL request if allowed → wait for landing. Run from the repository root with `gz_x500` SITL already running:

~~~bash
python -m simulation.mavsdk.waypoint_mission_flight
~~~

**Evidence status:** unit-tested only (`tests/test_x500_mission_telemetry.py`), with fake clocks and an in-memory fake vehicle. **Not run against PX4 SITL.** Unobserved: whether PX4 starts this mission (no explicit takeoff item) from the ground, which mode MAVSDK reports during the mission takeoff (if it is `TAKEOFF`, the monitor ends the attempt with `START_TIMEOUT` or `MODE_CHANGED`), whether `mission_progress` is reported at start or only on change (if not reported, the attempt ends `START_TIMEOUT` with no command), and the rate of the mode/armed/in-air streams relative to the 2 s age placeholder. The 0.2 s check interval and 120 s landing timeout are SITL placeholders.
