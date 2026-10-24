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
