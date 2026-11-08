# Validation evidence

This index separates source availability, automated checks, simulator runtime and physical-aircraft evidence.

| Record | Revision / location | What it establishes | Limit |
|---|---|---|---|
| Merged scaffold | [PR #5](https://github.com/travtrego/Wildlife-Drone-Program/pull/5), merge `2054580` | Initial configuration guards, smoke mission, six unit tests and CI | Code availability is not runtime or flight evidence |
| Latest inspected main CI | [Run 38680942078](https://github.com/travtrego/Wildlife-Drone-Program/actions/runs/38680942078), `4ded919` | Successful lint, compile and unit workflow | Workflow does not run PX4/Gazebo or MAVSDK runtime |
| Recorded SITL validation | [Immutable September 3 report](https://github.com/travtrego/Wildlife-Drone-Program/blob/2cb5102ae6bbae4c927ae33f87a21d0abc249a27/docs/SITL_VALIDATION_2026-09-03.md) | Three successful headless X500 runs; commands, versions, warnings and ULog checksums | Existing prerequisites/PX4 build on one laptop |
| Validated branch CI | [Run 33792886591](https://github.com/travtrego/Wildlife-Drone-Program/actions/runs/33792886591), `2cb5102` | Successful lint, compile and 13 tests | Separate from live SITL evidence; PR #6 merged October 18 as `56872a8` |
| X500 waypoint mission SITL | [November 1 record](SITL_VALIDATION_2026-11-01.md), `7ef6c3d` | Upload/read-back and monitored waypoint mission (preflight gate, start, completion, RTL, landing) passed once in headless `gz_x500` | One nominal run on the same laptop; PX4 revision and ULog checksum not recorded; failure paths not exercised in SITL |
| X500 failure paths + Coyote R6 watch SITL | [November 1 afternoon record](SITL_VALIDATION_2026-11-01_FAILURE_PATHS.md), `adcffd8` | Monitor ends correctly on Hold and RTL; PX4 reports `system_status` CRITICAL during a GPS-loss failsafe; observed stream rates. Found two bugs (HOLD before final progress; oldest-stream age revoking grants), fixed afterwards and unit-tested only | One session, one laptop; checksums not recorded; pilot takeover, airborne preflight refusal, live-grant revocation paths and QGC display not exercised |
| R6 grant forwarding, PX4 SIH hexacopter (cloud) | [November 8 record](SITL_VALIDATION_2026-11-08_SIH.md), PX4 `6041c961` | PX4 forwards a ground `COMMAND_LONG` (255/190 → 1/191) to the companion link; found and fixed a shared `mavsdk_server` port in the SITL sender | SIH, not Gazebo; watch's MAVSDK subscription still received nothing; on the ground only |
| X500 / Fighter / Coyote physical qualification | No completed acceptance record in inspected repository | Nothing yet established here | Ownership, installation, fit, power, endurance and real flight require their own records |

## Recorded runtime environment

The September 3 report records Windows 11/WSL2, Ubuntu 24.04.4, Python 3.12.3, MAVSDK 3.17.2, Gazebo 8.15.0 and PX4 `6041c961dd619b08f9a726a4052b1fadf1f98e94`. The final mission observed airborne state and at least 2.7m for a requested 3m before a five-second timed loiter and landing. Raw logs remain outside Git; checksums and paths are in the report.

A clean checkout/new virtual environment reproduced the workflow using installed prerequisites. Issue #4's checked “fresh machine” wording must not be read as evidence of a second independently provisioned machine. That broader exit criterion remains unproven.

## Current implementation boundary

Since PR #6 merged, default-branch smoke code binds explicitly to loopback, waits for airborne/altitude telemetry before loitering and fails on ended telemetry streams. The Coyote action gate (PR #8) is unit-tested only. The X500 waypoint upload/read-back check, the monitored waypoint flight and the preflight gate (`x500/flight/`, `simulation/mavsdk/waypoint_*.py`) passed one nominal headless SITL run on 2026-11-01 ([record](SITL_VALIDATION_2026-11-01.md)); their failure paths are unit-tested only. The Coyote MAVSDK telemetry pumps and R6 delegation watch (`coyote/autonomy/vehicle_link.py`) are unit-tested with fake streams and senders only. The HEARTBEAT `system_status` failsafe source (`coyote/autonomy/failsafe_source.py`) saw CRITICAL during one SITL GPS-loss failsafe; the R6 watch and the X500 monitor's failure endings ran once in SITL (afternoon record). The candidate R6 grant/revoke `COMMAND_LONG` transport (`coyote/autonomy/grant_transport.py`) is unit-tested with fake messages only; it has not received a command in SITL. The X500 return/landing watch after the RTL request (`x500/flight/return_monitor.py`), which now also requires disarm for the flight script's PASS, is unit-tested only.

Even explicit loopback is a network restriction, not proof that a vehicle is simulated. Do not bridge real hardware into this endpoint.

## Future evidence records

Record requirement, exact code/hardware configuration, procedure, acceptance criteria, result, log identifier/checksum and unresolved limits. CI is not SITL; SITL is not bench qualification; bench qualification is not flight acceptance. Keep test results separate from future test plans.
