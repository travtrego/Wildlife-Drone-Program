# SITL failure-path and Coyote watch session — 2026-11-01 (afternoon)

Second PX4 SITL session of the day, following [SITL_SESSION_CHECKLIST.md](../simulation/mavsdk/SITL_SESSION_CHECKLIST.md). The owner ran it on his laptop. This record was transcribed from his terminal screenshots. No real aircraft was connected or commanded. No arming check or failsafe was disabled. The only parameter changed was PX4's failure-injection switch `SYS_FAILURE_EN` (set to 1 for one test, then back to 0).

## Configuration

| Item | Value |
|---|---|
| Code revision | `adcffd8` (main after #26), confirmed with `git log -1 --oneline` |
| PX4 | `6041c961dd619b08f9a726a4052b1fadf1f98e94` (same as the 2026-09-03 runs), `HEADLESS=1 make px4_sitl gz_x500` |
| Gazebo | Gazebo Sim 8.15.0 |
| Machine | Owner laptop `TravisLaptop`, Ubuntu in WSL2, project `.venv` (Python 3.12) reinstalled with the validated constraints; `pytest` all passed before the runs |
| Endpoint | `udpin://127.0.0.1:14540` (default `sitl_config.json`); PX4 reported its onboard link as udp 14580 → remote 14540 |
| ULogs | `2026-11-01/18_35_31.ulg` (A0), `18_39_32.ulg` (A3), `18_40_36.ulg` (A5), `18_41_48.ulg` (A4), `18_46_02.ulg` (B GPS failure). Raw logs stay outside Git. **Checksums were not recorded.** |

## Part A — X500 monitored waypoint mission (`waypoint_mission_flight`)

| Run | Action in the PX4 shell | Script result | PX4 result |
|---|---|---|---|
| A0 nominal | none | `ended MODE_CHANGED mode HOLD before completion`, no follow-up, `FAIL` | Flew the whole mission ("Mission finished, loitering"). After the script exited: "Connection to ground station lost" → failsafe Hold 5 s → RTL → landed, disarmed |
| A3 Hold | `commander mode auto:loiter` after takeoff | `ended MODE_CHANGED mode HOLD before completion`, no follow-up | Link-loss failsafe → RTL → landed after the script exited |
| A5 RTL | `commander mode auto:rtl` after takeoff | `ended PX4_RECOVERY_MODE PX4 mode RETURN_TO_LAUNCH`, no follow-up | RTL, landed, disarmed |
| A4 POSCTL | `commander mode posctl`, then `commander mode auto:rtl` | `ended PX4_RECOVERY_MODE` (from the RTL) | **POSCTL refused** (negative tone; no RC/joystick in SITL). RTL climbed to 31 m, landed |
| A2 airborne start | `commander takeoff` before the script | not run | **Arming denied:** "Resolve system health failures first" (PX4 needs a GCS connection; none was connected). Test skipped |

Findings:

- **Bug (A0):** the nominal mission completed in PX4, but PX4 reported HOLD before MAVSDK mission progress reported the last item reached. So the monitor ended `MODE_CHANGED`. The 2026-11-01 overnight pass got the two messages in the other order. The fix in this change waits up to 3 s (placeholder) for completion when HOLD is reported while airborne on the last item.
- A3 and A5 behaved as designed: the monitor ended, and the script sent no follow-up command.
- Whenever the script exited during or after a flight, PX4's own data-link-loss failsafe brought the vehicle home and landed it.
- Not exercised: pilot takeover (no RC in SITL), the preflight refusal while armed or airborne (PX4 won't arm without a GCS), low battery, stall/timeout and stale telemetry.

## Part B — Coyote R6 watch (`coyote_delegation_watch`)

The watch ran twice, about 71 s and 84 s. In the first run it was idle on the ground, followed by `g` (grant). In the second, the PX4 shell ran `commander takeoff` (armed by internal command; takeoff 3 m), then `param set SYS_FAILURE_EN 1` and `failure gps off`, then `failure gps ok` and `param set SYS_FAILURE_EN 0`.

Observed stream rates (watch summary, both runs):

| Stream | Rate |
|---|---|
| flight_mode, armed, in_air | 1.00 Hz |
| position | ≈ 50 Hz |
| battery | ≈ 0.6 Hz |
| autopilot HEARTBEAT | 1.00 Hz, only sender `(sysid 1, compid 1)` |

HEARTBEAT `fields_json` uses **integers** for enums, for example `{"message_id":0,"message_name":"HEARTBEAT","autopilot":12,"base_mode":29,"custom_mode":33816576,"mavlink_version":3,"system_status":3,"type":2}`.

`system_status` values seen in the second run (count): `3` STANDBY 16, `4` ACTIVE 38, **`5` CRITICAL 7**, `0` UNINIT 23.

Findings:

- **PR #25's assumption holds for this PX4 build.** During the GPS-loss failsafe ("Failsafe: blind land", "Failsafe activated"), PX4 reported `system_status` 5 (CRITICAL), which the source maps to `failsafe_active = True`. Disarmed it was 3, armed 4. PX4 landed the vehicle itself.
- **`system_status` 0 (UNINIT) was reported on the ground after the GPS failure**, while PX4 preflight checks were failing ("no heading reference", "GPS Vertical Pos Drift too high"). The source maps 0 to unknown, which refuses grants, so no change is needed. That PX4 uses 0 this way was not expected.
- **Bug:** the grant was accepted at 66.02 s and revoked at 66.74 s with `PX4 TELEMETRY LOST` on a healthy link. The snapshot age was the *oldest* stream's age, and battery arrives only every ~1.7 s, so the age alternated between about 0.4 and 1.4 s against the 1 s limit. The fix in this change gives each stream its own staleness limit and uses the newest update as the link age.
- The alert line was reported sent (`alert sent (WARNING): COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST`): the transport accepted it. No QGroundControl was connected, so whether QGC displays it is still unobserved.
- The 1 Hz heartbeat confirms that the 2.5 s failsafe-age placeholder (`HEARTBEAT_TRACKER_CONFIG`) is needed.
- Because of the revocation bug, no other R6 revocation path was exercised with a live grant: flight ended, pilot mode, RTL, failsafe and simulator pause.

## What this does not establish

- One session on one laptop. ULog checksums not recorded.
- The fixes in this change are unit-tested only and have not been rerun in SITL.
- Nothing about QGroundControl display, Coyote hardware, bench tests or real flight.
