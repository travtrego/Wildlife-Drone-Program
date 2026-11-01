# X500 SITL waypoint mission record — 2026-11-01

First run of the X500 flight-layer mission code against PX4 SITL. The owner ran it on his laptop; the record below was transcribed from his terminal screenshots. No real aircraft was connected or commanded. No PX4 source, arming check or failsafe parameter was changed.

## Configuration

| Item | Value |
|---|---|
| Code revision | `7ef6c3d` (main, after #23), confirmed with `git log -1 --oneline` |
| Machine | Owner laptop `TravisLaptop`, Ubuntu shell, the same laptop as the [2026-09-03 runs](SITL_VALIDATION_2026-09-03.md) |
| Python env | Existing `.venv` (Python 3.12), reinstalled with `pip install -e ".[dev,sim]" -c simulation/mavsdk/constraints-validated.txt`; MAVSDK 3.17.2 |
| PX4 | Existing build in `~/src/PX4-Autopilot`, `HEADLESS=1 make px4_sitl gz_x500`. **PX4 and Gazebo revisions were not recorded for this run.** |
| Endpoint | `udpin://127.0.0.1:14540` (default `sitl_config.json`) |
| Mission | `simulation/mavsdk/x500_waypoint_square.json`: 5 waypoints, 20 m square, 10 m above home, 3 m/s |
| Limits | `X500_SITL_MISSION_LIMITS`, `X500_SITL_PREFLIGHT_LIMITS` (40 % battery, 2 s age), `x500_sitl_monitor_settings` — all model inputs / SITL placeholders |

PX4 startup showed the usual SITL warnings before a client connected ("Preflight Fail: No connection to the GCS", "no heading reference"). PX4 opened log `./log/2026-11-01/02_27_42.ulg` at startup. Raw logs stay outside Git, and no checksum was recorded.

## Commands and observed output

~~~text
$ .venv/bin/python -m simulation.mavsdk.waypoint_upload_check
Connecting to PX4 SITL at udpin://127.0.0.1:14540 ...
Home 47.3979711, 8.5461634
PASS: 5 waypoints uploaded and read back unchanged (mission not started).

$ .venv/bin/python -m simulation.mavsdk.waypoint_mission_flight
Connecting to PX4 SITL at udpin://127.0.0.1:14540 ...
Mission of 5 items verified; arming (PX4 checks enabled) ...
Mission start requested; monitoring ...
Monitor: completed  reached item 5/5
Requesting PX4 RETURN_TO_LAUNCH ...
PASS: simulated waypoint mission completed, RTL requested, vehicle landed.
~~~

## What this establishes (one run, simulation only)

- **Preflight gate (#22):** it passed in both scripts and before arm. PX4 SITL reported every required health flag, including `is_armable`, as True, and battery at or above 40 %, by the time home was valid.
- **Upload/read-back (#16):** PX4 returned all 5 items within the read-back tolerances, including speed and fly-through.
- **Mission start:** PX4 started the mission from the ground with no explicit takeoff item.
- **Monitor and telemetry (#18, #20):** the monitor reached `COMPLETED` at item 5/5. It did not end with `START_TIMEOUT`, `MODE_CHANGED` or `TELEMETRY_STALE`. So, under the current placeholders, the mode reported during the mission takeoff was accepted, `mission_progress` was delivered, and the streams stayed within the 2 s age limit.
- **Follow-up:** the follow-up check allowed the RTL request, and the vehicle reported landed within the 120 s timeout.

## What it does not establish

- The specific flight modes, `mission_progress` values at start, stream rates and per-item times were not printed, so the timing placeholders are still not measured.
- Only the nominal path ran. Preflight refusals (armed, airborne, low battery), stall/timeout RTL recommendations, pilot takeover, PX4 failsafe modes and stale telemetry were not exercised in SITL.
- One run on one laptop. No PX4 revision or ULog checksum was recorded. Not a second machine.
- Nothing about Coyote code, hardware, bench tests or real flight.
