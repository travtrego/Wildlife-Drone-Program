# SITL observation 2026-11-08: R6 grant loop on the laptop (PX4 + Gazebo, X500 model)

**Observation only, not a PASS.** Run by the owner (Travis) on his laptop, guided live from a Claude session; results transcribed from terminal screenshots he shared.

## Environment

- Laptop: Windows 11 / WSL2 Ubuntu, same setup as the [September 3](https://github.com/travtrego/Wildlife-Drone-Program/blob/2cb5102ae6bbae4c927ae33f87a21d0abc249a27/docs/SITL_VALIDATION_2026-09-03.md) and November 1 records. PX4 revision and Gazebo version **not re-recorded** this session.
- Repository: `main` at `cd2d374` (after PR #35), `pip install -e ".[dev,sim]"` with the validated constraints (adds pymavlink 2.4.50); `pytest -q` all passed.
- PX4: `HEADLESS=1 make px4_sitl gz_x500`. MAVLink instances as printed: ground 18570→14550, onboard 14580→14540, second onboard 14280→14030, gimbal 13030→13280; localhost only.
- Terminal 1: `python -m simulation.mavsdk.coyote_delegation_watch --grant-source command-link` (STATUSTEXT alerts sent). Terminal 3: `python -m simulation.mavsdk.coyote_ground_sender` (fresh sequence file). X500 model used because it is the laptop's working model; the R6 logic is aircraft-independent.
- ULogs named by PX4: `2026-11-08/02_57_28.ulg`, `03_12_10.ulg`, `03_12_35.ulg` (checksums not recorded).

## Observed

| # | Action | Observed |
|---|---|---|
| L1 | `commander mode auto:loiter`; sender `g` | `grant #1: companion ACCEPTED`. MAVSDK on the ground also logged `Received ack for not-existing command: 31010! Ignoring...` (as in the cloud run); the reply was still shown |
| L2 | `commander mode posctl`; `g`; back to `auto:loiter` | `grant #2: companion REFUSED (MAV_RESULT 2)` |
| L3 | `commander arm`; `g`; `commander takeoff`; hover; `commander land` | Watch: hovering `mode=HOLD armed=True in_air=True alt=3.0m ... delegated=True`; at 567.34 s `delegated -> False` and `alert sent (WARNING): COYOTE AUTONOMY OFF: PX4 RTL/LAND` within one status interval of LAND. Stayed revoked through touchdown and disarm |
| L4 | `commander arm`, (grant, timing unconfirmed), PX4 auto-disarmed (`Disarmed by auto preflight disarming`); `commander takeoff` re-armed and took off; `commander mode auto:rtl` | PX4: RTL climbed to 4 m, landed at home, `Disarmed by landing`. The watch lines around this flight were not captured. A grant sent before the auto-disarm would have been revoked by that disarm (`FLIGHT_ENDED`), so this run is **not** evidence for revocation on RTL in the air |
| — | Watch summary after `q` | ~829 s: flight_mode/armed 1.00 Hz, in_air 5.00 Hz, position 50.00 Hz, battery 0.50 Hz, autopilot heartbeat 1.00 Hz, `command_long 20`. Heartbeat senders (1, 1): 829 and **(1, 191): 770** (the companion's own heartbeat seen back). `system_status` 3: 572, 0: 179 (one example with `custom_mode` 196608, POSCTL, disarmed), 4: 78. 21 events |

## What this establishes

- On the laptop's Gazebo setup, the second-link receive path (PR #35) receives the ground tool's grant, and the ground tool shows the companion's reply: accepted in Hold, refused in POSCTL.
- One airborne case: authority granted on the ground was held in a 3 m hover and revoked with the ground alert as soon as PX4 switched to LAND.

## Not established / follow-ups

- Revocation on RTL in the air (L4 inconclusive), on pilot takeover in the air, on GPS-loss failsafe and on link loss in this mode.
- Whether QGroundControl displays the STATUSTEXT alert (QGC was closed).
- After the sender quit, PX4 reported `system_status` 0 (preflight fail: no GCS) and the watch showed `failsafe=None`, which would refuse any new grant. Consistent with the November 1 observation.
- Small script issue seen: in command-link mode the watch's help text for an unknown key still says "g = grant (local stand-in)", and the first `q` did not quit (a stray character); cosmetic.
- PX4 revision, Gazebo version and ULog checksums to be recorded next session.
