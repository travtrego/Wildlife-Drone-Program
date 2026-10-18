# Validation evidence

This index separates source availability, automated checks, simulator runtime and physical-aircraft evidence.

| Record | Revision / location | What it establishes | Limit |
|---|---|---|---|
| Merged scaffold | [PR #5](https://github.com/travtrego/Wildlife-Drone-Program/pull/5), merge `2054580` | Initial configuration guards, smoke mission, six unit tests and CI | Code availability is not runtime or flight evidence |
| Latest inspected main CI | [Run 38680942078](https://github.com/travtrego/Wildlife-Drone-Program/actions/runs/38680942078), `4ded919` | Successful lint, compile and unit workflow | Workflow does not run PX4/Gazebo or MAVSDK runtime |
| Recorded SITL validation | [Immutable September 3 report](https://github.com/travtrego/Wildlife-Drone-Program/blob/2cb5102ae6bbae4c927ae33f87a21d0abc249a27/docs/SITL_VALIDATION_2026-09-03.md) | Three successful headless X500 runs; commands, versions, warnings and ULog checksums | Existing prerequisites/PX4 build on one laptop |
| Validated branch CI | [Run 33792886591](https://github.com/travtrego/Wildlife-Drone-Program/actions/runs/33792886591), `2cb5102` | Successful lint, compile and 13 tests | Separate from live SITL evidence; PR #6 remains open as of October 17 |
| X500 / Fighter / Coyote physical qualification | No completed acceptance record in inspected repository | Nothing yet established here | Ownership, installation, fit, power, endurance and real flight require their own records |

## Recorded runtime environment

The September 3 report records Windows 11/WSL2, Ubuntu 24.04.4, Python 3.12.3, MAVSDK 3.17.2, Gazebo 8.15.0 and PX4 `6041c961dd619b08f9a726a4052b1fadf1f98e94`. The final mission observed airborne state and at least 2.7m for a requested 3m before a five-second timed loiter and landing. Raw logs remain outside Git; checksums and paths are in the report.

A clean checkout/new virtual environment reproduced the workflow using installed prerequisites. Issue #4's checked “fresh machine” wording must not be read as evidence of a second independently provisioned machine. That broader exit criterion remains unproven.

## Current implementation boundary

Default-branch smoke code still sleeps immediately after requesting takeoff, allows blank/wildcard UDP listeners on port 14540, and can fall through on ended telemetry streams. PR #6 introduces explicit loopback binding, airborne/altitude gates and ended-stream failures. Refer to that PR for the implementation review; this documentation cleanup does not merge it or transplant flight behavior.

Even explicit loopback is a network restriction, not proof that a vehicle is simulated. Do not bridge real hardware into this endpoint.

## Future evidence records

Record requirement, exact code/hardware configuration, procedure, acceptance criteria, result, log identifier/checksum and unresolved limits. CI is not SITL; SITL is not bench qualification; bench qualification is not flight acceptance. Keep test results separate from future test plans.
