# SITL session checklist: X500 failure paths and Coyote R6 watch

A plan for one laptop session (about 45–60 minutes). **Nothing here has been run yet.** Every "expected" line is what the unit-tested code should do, written down before the run so the result can be compared against it. PX4 commands marked *(unverified)* come from PX4 documentation and memory, not from a run on this setup. If PX4 refuses one or prints something unexpected, write down exactly what it said. That is a useful result too.

Simulation only. Do not connect a real aircraft, radio or MAVLink bridge. Do not disable arming checks or failsafes. The only parameters changed below are simulator settings (`SIM_BAT_*`), PX4's failure-injection switch (`SYS_FAILURE_EN`), the SITL geofence (`GF_*`, which *enables* a PX4 limit) and the SITL RTL altitude (`RTL_RETURN_ALT`, lowered so the return stays inside that geofence). Reset them at the end.

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

Before any `waypoint_mission_flight` run, turn on a PX4 geofence. The flight script refuses the mission while the PX4 geofence is disabled (`0`, the PX4 default) or `GF_ACTION` is not Hold/Return/Land (owner decision 2026-11-06). These are **simulator settings** at or above the X500 SITL companion limits (100 m, 30 m), not values for a real aircraft:

~~~text
param set GF_MAX_HOR_DIST 150
param set GF_MAX_VER_DIST 40
param set GF_ACTION 3
param set RTL_RETURN_ALT 20
~~~

*(unverified: parameter names and `GF_ACTION` numbering are from PX4 documentation, not checked against this build.)* `RTL_RETURN_ALT` (PX4 default 60 m) must not be above `GF_MAX_VER_DIST`, or the script refuses because PX4's own return would climb into the fence; 20 m is a simulator setting below the 30 m companion ceiling, not a value for a real aircraft. Check with `param show GF_*` and `param show RTL_RETURN_ALT` and record the values. If the script refuses with `GF_... = 0` or `RTL_RETURN_ALT ... above`, this step was missed or did not stick after a restart. At the end of the session: `param reset GF_MAX_HOR_DIST`, `param reset GF_MAX_VER_DIST`, `param reset GF_ACTION`, `param reset RTL_RETURN_ALT`.

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

For each run, copy the full terminal 2 output and the PX4 lines from terminal 1 around the event. Since the mission-trace change, terminal 2 also prints every mode/armed/in-air/progress/monitor change and a `Mission trace` summary at exit; include the whole summary.

Learned 2026-11-01: PX4 refuses `commander arm`/`takeoff` from the shell unless a MAVSDK client (ground station) is connected, so A1/A2 need the watch script or QGC running; POSCTL is refused without RC. See the [afternoon record](../../docs/SITL_VALIDATION_2026-11-01_FAILURE_PATHS.md).

Monitor time-budget faults (the only path where the script sends a command because of a monitor fault: the proposed RTL). Added after this checklist was first written; *not yet run*. The flags only shorten the monitor's SITL placeholders (60 s per item, 300 s mission); longer values are refused and nothing is changed in PX4. These runs print `INJECTED FAULT PATH OK` or `FAIL`, never `PASS`.

| # | What to do | Expected script result | Then |
|---|---|---|---|
| A8 | `python -m simulation.mavsdk.waypoint_mission_flight --inject-mission-budget-s 20` | Banner `SITL FAULT INJECTION ...`; about 20 s after PX4 first reports MISSION: `ended mission_timeout`, `Requesting PX4 RETURN_TO_LAUNCH`, `Return watch: landed`, `INJECTED FAULT PATH OK`. If the vehicle is still climbing or the mission finishes first, record the trace (item times) and pick a value from it | — |
| A9 | `... --inject-item-budget-s N`, with N taken from the A0/A8 trace: longer than the takeoff item, shorter than a 20 m leg | `ended item_stalled`, RTL requested, `Return watch: landed`, `INJECTED FAULT PATH OK`. If N is shorter than the takeoff item the stall fires during the climb; record what PX4 and the return watch did | — |

Not covered: a real stall or timeout (the vehicle here flies normally; only the budget is shortened), and a real RC pilot takeover.

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

### Part B-M: grant over MAVLink (optional, after Part B)

This checks whether a ground-station `COMMAND_LONG` reaches the companion through PX4. Start PX4 fresh and close QGroundControl, because the sender uses the ground port 14550. In terminal 2, start the watch as the companion. In terminal 3, start the SITL-only ground sender:

~~~bash
python -m simulation.mavsdk.coyote_delegation_watch --grant-source mavlink   # terminal 2
python -m simulation.mavsdk.coyote_ground_sender                            # terminal 3
~~~

| # | What to do | Expected watch output (terminal 2) |
|---|---|---|
| BM1 | Wait 30 s; `commander mode auto:loiter` if PX4 is in a pilot mode | Status lines as in B1. The summary later shows whether `(1, 191)` or `(255, 190)` heartbeats appeared |
| BM2 | `g` in terminal 3 | `ground command grant #N ... accepted=True`. **If nothing appears, PX4 did not forward the command (or MAVSDK did not deliver it). Record that; it is the main unknown** |
| BM3 | `r` in terminal 3 | `ground command revoke`, `delegated -> False`, NOTICE alert |
| BM4 | `g` in terminal 3, then quit the sender (`q`) | Whether the watch notices: it should not revoke on sender exit alone (the command stream is a PX4 subscription). Record what happens |
| — | `q` in terminal 2 | Summary includes the `command_long` count |

*(unverified: the 14550 ground port and PX4 command forwarding between its ground and onboard links come from PX4 documentation, not from this build.)* Copy both terminals' output.

**Update 2026-11-08 (cloud SIH run, [record](../../docs/SITL_VALIDATION_2026-11-08_SIH.md)):** with `--grant-source mavlink` the watch received nothing, although PX4 did forward the command. Use `--grant-source command-link` instead: the watch then listens for the command on PX4 SITL's second onboard link, and the sender prints the companion's reply (`companion ACCEPTED`, `REFUSED` or `NO REPLY`). Repeat BM1–BM4 with it on the laptop's Gazebo setup, and add one grant in POSCTL (expect `REFUSED`). Install the sim extras again first (`pymavlink` was added).

## Send back

The terminal 2 output from every run (especially the Part B summary), the PX4 lines around each event, the three version lines from step 0, the ULog checksums, and whether QGC showed the alerts. I'll turn them into a dated record in `docs/` and fix any assumption that turns out wrong.
