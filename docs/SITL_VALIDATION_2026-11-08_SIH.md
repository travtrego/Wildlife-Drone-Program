# SITL observation 2026-11-08: R6 grant forwarding (PX4 SIH hexacopter, cloud)

**Observation only, not a PASS.** Run in the Claude cloud session, not on the owner's laptop.

## Environment

- Repository: main `e223891` plus this branch (`claude/coyote-2026-11-08-sitl-grant-forwarding`): sender port fix, then the command-link receive path and reply display.
- PX4 `6041c961dd619b08f9a726a4052b1fadf1f98e94` (same as the laptop records), `make px4_sitl_default`, run with `PX4_SIM_MODEL=sihsim_hex PX4_SIMULATOR=sihsim` (airframe 10044, built-in SIH physics, **no Gazebo**). Ubuntu 24.04, 2 CPU cores, Python 3, MAVSDK-Python 3.17.2, pymavlink 2.4.50.
- All MAVLink on localhost. PX4 mode set to Hold before the runs; vehicle disarmed and on the ground throughout. No arming, failsafe or safety parameter changed.

## Runs (checklist Part B-M)

| Run | Setup | Observed |
|---|---|---|
| 1 | `coyote_delegation_watch --grant-source mavlink --no-status-text` + `coyote_ground_sender` (g, r, g) | Sender printed "sent" three times; watch `command_long 0`. PX4 log: `Ignore command 31010 from 1/191 to 1/191` ×3. **Bug:** both scripts' `System()` used the default `mavsdk_server` port 50051, so the sender drove the watch's server and the command left as 1/191 on the companion link |
| 2 | Same, sender given its own `mavsdk_server` port (50052) | PX4: `GCS connection regained`, no "Ignore command". Watch still `command_long 0`; heartbeat senders only (1, 1) |
| 3 | pymavlink listener on 14540 as 1/191 (sending a 1 Hz heartbeat) in place of the watch + sender (g, r) | Received `COMMAND_LONG from 255/190 -> 1/191 cmd=31010 p1=1.0 p2=3.0` and `p1=2.0 p2=0.0`. **PX4 forwards the grant and revoke to the companion link** |
| 4 | PX4 restarted (background processes do not survive between turns in this environment). pymavlink listener on PX4's second onboard link (sends to 14280 from 14030) | Received the grant `255/190 -> 1/191`, sequence 4; also forwarded `HEARTBEAT` from 255/190 |
| 5 | `coyote_delegation_watch --grant-source command-link --no-status-text` (MAVSDK telemetry on 14540, commands on the second link) + sender: g, r, g, `commander mode posctl`, g, `commander mode auto:loiter`, g | Grant #5 accepted, `COMMAND_ACK result=0 seq=5`; revoke → NOTICE alert, ack 0; grant #6 accepted; POSCTL (no RC): PX4 `system_status` went 0 → failsafe unknown → revoked `FAILSAFE STATE UNKNOWN` (WARNING); grant #7 refused (`failsafe state unknown`), `COMMAND_ACK result=2`; back in Hold, grant #8 accepted. Watch: `command_long 5`, heartbeat senders (1, 1) and (1, 191) |
| 6 | Same as 5 with the sender waiting up to 2 s for the reply | Sender printed `grant #9: companion ACCEPTED`, `revoke: companion ACCEPTED`, `grant #10: companion REFUSED (MAV_RESULT 2)` (in POSCTL), `grant #11: companion ACCEPTED`. MAVSDK on the ground also logged `Received ack for not-existing command: 31010! Ignoring...` each time; its `mavlink_direct` subscription still delivered the ack |

## What this establishes

- With PX4's default SITL `-f` forwarding, a ground-station `COMMAND_LONG` addressed to 1/191 reaches the onboard link once a 1/191 component has been seen there.
- The SITL sender needs its own `mavsdk_server` port when run beside the watch (fixed on the branch above).
- With the command on a second plain-MAVLink link, the full R6 command loop worked on the ground, disarmed: grant, revoke, refusal in a pilot mode, re-grant, and the `COMMAND_ACK` reply (#33) shown on the ground tool.
- With no RC, PX4 reported `system_status` 0 after switching to POSCTL, so the revocation reason was `FAILSAFE STATE UNKNOWN`, not `PILOT TAKEOVER` (the mode stream shows POSCTL a moment later). Either way authority went off.

## Not established / open

- Why the MAVSDK `mavlink_direct` subscription in the watch did not deliver the forwarded command (likely: it only reports messages from the autopilot system, not from 255/190; unconfirmed). The owner chose (2026-11-08) a separate plain-MAVLink listener; on the real aircraft that needs a second Pixhawk-to-Jetson link or a router, which is unverified.
- SIH is not Gazebo; laptop runs remain the reference. No ULog checksums recorded. Airborne revocation paths and QGC display not exercised; the vehicle stayed on the ground and disarmed.
