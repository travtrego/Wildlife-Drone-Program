# SITL session checklist: X500 failure paths and Coyote R6 watch

A plan for one laptop session (about 45–60 minutes). **Nothing here has been run yet.** Every "expected" line is what the unit-tested code should do, written down before the run so the result can be compared against it. PX4 commands marked *(unverified)* come from PX4 documentation and memory, not from a run on this setup. If PX4 refuses one or prints something unexpected, write down exactly what it said. That is a useful result too.

Simulation only. Do not connect a real aircraft, radio or MAVLink bridge. Do not disable arming checks or failsafes. The only parameters changed below are simulator settings (`SIM_BAT_*`) and PX4's failure-injection switch (`SYS_FAILURE_EN`). Reset them at the end.

## 0. Setup and versions (record once)

Terminal 2 (project):

~~~bash
cd ~/src/Wildlife-Drone-Program
git fetch origin
git checkout claude/coyote-2026-11-01-sitl-watch   # contains main + PR #25 + the watch script
source .venv/bin/activate
pip install -e ".[dev,sim]" -c simulation/mavsdk/constraints-validated.txt
pytest -q
git log -1 --oneline                                  # record
git -C ~/src/PX4-Autopilot rev-parse HEAD             # record (missing from the 11-01 record)
gz sim --version | head -1                            # record
~~~

Terminal 1 (PX4):

~~~bash
cd ~/src/PX4-Autopilot
HEADLESS=1 make px4_sitl gz_x500
~~~

Wait for "Startup script returned successfully". Terminal 1 is now the PX4 shell (`pxh>`), where the `commander ...` lines below are typed.

After each run, record the newest ULog's name and checksum:

~~~bash
ls -t ~/src/PX4-Autopilot/build/px4_sitl_default/rootfs/log/*/*.ulg | head -1 | xargs sha256sum
~~~

If a run leaves the vehicle in an odd state, stop PX4 with Ctrl+C in terminal 1 and start it again. That is always safe here.

## Part A: X500 mission failure paths (code already on main)

Run the mission with `python -m simulation.mavsdk.waypoint_mission_flight` in terminal 2. In terminal 1, type the PX4 command once the script prints `Mission start requested; monitoring ...` and the vehicle has passed waypoint 1 or 2.

| # | What to do | Expected script result | Then |
|---|---|---|---|
| A0 | Nothing (nominal repeat, now with versions and checksum) | `Monitor: completed`, RTL requested, `PASS` | — |
| A1 | Before starting the script: `commander arm`, then run the script within ~10 s | Preflight gate refuses before upload (armed vehicle); nothing sent | PX4 should auto-disarm. If PX4 refuses to arm, record its message and skip |
| A2 | Before the script: `commander takeoff`, wait until it hovers, then run the script | Preflight refusal (armed/airborne); no upload | `commander land` |
| A3 | Mid-mission: `commander mode auto:loiter` (Hold) | `Monitor: ended mode_changed`, `No follow-up command`, `FAIL` (expected) | `commander mode auto:rtl` |
| A4 | Mid-mission: `commander mode posctl` | `ended pilot_takeover`, no follow-up. *(PX4 may refuse POSCTL with no RC/joystick. Record what it says)* | `commander mode auto:rtl` |
| A5 | Mid-mission: `commander mode auto:rtl` | `ended px4_recovery_mode`, no follow-up; PX4 lands on its own | — |
| A6 | Before the script: `param set SIM_BAT_MIN_PCT 10` and `param set SIM_BAT_DRAIN 30` *(unverified semantics)*, then run | Either the preflight gate refuses (battery below 40%), or PX4's own low-battery reaction starts mid-mission and the monitor ends `px4_recovery_mode`. Record PX4's battery messages | `param reset SIM_BAT_MIN_PCT` and `param reset SIM_BAT_DRAIN`, then restart PX4 |
| A7 | Mid-mission: `mavlink stop -u 14580` *(unverified; stops the link MAVSDK uses)* | About 2 s later, `ended telemetry_stale`, no follow-up. PX4 continues on its own and may trigger its own link-loss reaction. Record it | Restart PX4 |

For each run, copy the full terminal 2 output and the PX4 lines from terminal 1 around the event.

Learned 2026-11-01: PX4 refuses `commander arm`/`takeoff` from the shell unless a MAVSDK client (ground station) is connected, so A1/A2 need the watch script or QGC running; POSCTL is refused without RC. See the [afternoon record](../../docs/SITL_VALIDATION_2026-11-01_FAILURE_PATHS.md).

Not covered: per-item stall and mission timeout (no easy way to induce them without changing code), and a real RC pilot takeover.

## Part B: Coyote R6 watch (new script; sends no flight commands)

Start PX4 fresh. In terminal 2:

~~~bash
python -m simulation.mavsdk.coyote_delegation_watch
~~~

It prints a status line every second, an event line on every change, and a summary when you type `q` + Enter. You can also press Ctrl+C, and the summary still prints. Keys (type, then Enter): `g` = grant (a local stand-in for the ground-station command), `r` = operator revoke, `q` = quit. You fly the vehicle from terminal 1. If QGroundControl is open and connected, check whether the `COYOTE AUTONOMY OFF: ...` alerts appear in it. Add `--no-status-text` to print the alerts without sending them.

| # | What to do | Expected watch output |
|---|---|---|
| B1 | Wait 30 s on the ground | `system_status 3` (STANDBY) → `failsafe False`; heartbeat ≈1 Hz in the summary |
| B2 | `g` | `accepted=True`. If refused for a pilot mode (PX4 may boot in POSCTL), type `commander mode auto:loiter` in terminal 1, then `g` again |
| B3 | `r` | `delegated -> False`, `alert sent (NOTICE): ...` |
| B4 | `commander arm`, `g`, `commander takeoff`; wait for hover; `commander land` | `system_status 4` (ACTIVE) after arming. Revocation on landing: record which reason comes first (LAND mode or flight ended) |
| B5 | Takeoff again, `g` while hovering, then `commander mode posctl` | `PILOT TAKEOVER` alert, or PX4 refuses the switch (record) |
| B6 | Hovering, `g`, then `commander mode auto:rtl` | Revoked, `PX4 RTL/LAND` alert |
| B7 | Hovering, `g`, then `param set SYS_FAILURE_EN 1` and `failure gps off` *(failure injection; unverified)* | **The key check for PR #25:** does `system_status 5` (CRITICAL) appear, and which revocation comes first? Then `failure gps ok`, `commander land`, `param set SYS_FAILURE_EN 0` |
| B8 | Landed and disarmed, `commander mode auto:loiter`, `g`, then Ctrl+Z in terminal 1 (pauses PX4 and Gazebo) | About 1 s later: `delegated -> False`, `PX4 TELEMETRY LOST`. Then `fg` in terminal 1 to resume |
| — | `q` | Summary: stream rates, HEARTBEAT senders, every `system_status` value with its raw JSON |

## Send back

The terminal 2 output from every run (especially the Part B summary), the PX4 lines around each event, the three version lines from step 0, the ULog checksums, and whether QGC showed the alerts. I'll turn them into a dated record in `docs/` and fix any assumption that turns out wrong.
