# SITL observation 2026-11-08: R6 grant forwarding (PX4 SIH hexacopter, cloud)

**Observation only, not a PASS.** Run in the Claude cloud session, not on the owner's laptop.

## Environment

- Repository: main `e223891` plus the sender port fix on branch `claude/coyote-2026-11-08-sitl-grant-forwarding`.
- PX4 `6041c961dd619b08f9a726a4052b1fadf1f98e94` (same as the laptop records), `make px4_sitl_default`, run with `PX4_SIM_MODEL=sihsim_hex PX4_SIMULATOR=sihsim` (airframe 10044, built-in SIH physics, **no Gazebo**). Ubuntu 24.04, 2 CPU cores, Python 3, MAVSDK-Python 3.17.2, pymavlink (listener only).
- All MAVLink on localhost. PX4 mode set to Hold before the runs; vehicle disarmed and on the ground throughout. No arming, failsafe or safety parameter changed.

## Runs (checklist Part B-M)

| Run | Setup | Observed |
|---|---|---|
| 1 | `coyote_delegation_watch --grant-source mavlink --no-status-text` + `coyote_ground_sender` (g, r, g) | Sender printed "sent" three times; watch `command_long 0`. PX4 log: `Ignore command 31010 from 1/191 to 1/191` ×3. **Bug:** both scripts' `System()` used the default `mavsdk_server` port 50051, so the sender drove the watch's server and the command left as 1/191 on the companion link |
| 2 | Same, sender given its own `mavsdk_server` port (50052) | PX4: `GCS connection regained`, no "Ignore command". Watch still `command_long 0`; heartbeat senders only (1, 1) |
| 3 | pymavlink listener on 14540 as 1/191 (sending a 1 Hz heartbeat) in place of the watch + sender (g, r) | Received `COMMAND_LONG from 255/190 -> 1/191 cmd=31010 p1=1.0 p2=3.0` and `p1=2.0 p2=0.0`. **PX4 forwards the grant and revoke to the companion link** |

## What this establishes

- With PX4's default SITL `-f` forwarding, a ground-station `COMMAND_LONG` addressed to 1/191 reaches the onboard link once a 1/191 component has been seen there.
- The SITL sender needs its own `mavsdk_server` port when run beside the watch (fixed on the branch above).

## Not established / open

- Why the MAVSDK `mavlink_direct` subscription in the watch did not deliver the forwarded command (likely: it only reports messages from the autopilot system, not from 255/190; unconfirmed). Needs an owner choice of companion receive path before more code.
- SIH is not Gazebo; laptop runs remain the reference. No ULog checksums recorded. Airborne revocation paths, COMMAND_ACK (#33, not wired) and QGC display not exercised.
