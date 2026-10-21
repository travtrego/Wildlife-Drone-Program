# X500 V2 Reference Platform

## Role
The X500 is the program's reference and learning aircraft. Keep the ARF propulsion and mechanical system stock unless a measured limitation justifies a change.

## Initial hardware baseline
- Holybro X500 V2 ARF
- stock 2216 KV920 motors
- stock 20A BLHeli-S ESCs
- stock 1045 propellers
- stock PDB
- Pixhawk 6C class flight controller
- PM02 V3 class power module
- M10 GNSS
- 915 MHz SiK telemetry

## Development sequence

**Scope (owner decision 2026-10-21):** the X500 is a waypoint-autonomy aircraft only. It carries no Jetson and runs no perception or AI mission logic; that work is Coyote-only. The X500 proves the multirotor flight layer that Coyote reuses: PX4 takeoff, waypoint missions, landing and RTL, telemetry checks, mission upload/verification and the companion-request safety gate.

1. Mechanical inspection and assembly
2. Props-off avionics integration
3. PX4 configuration
4. Manual/reference flight
5. QGroundControl logging and review
6. MAVSDK Python takeoff / land / waypoint experiments
7. Autonomous waypoint missions with logged acceptance criteria
8. Promote stable flight-layer modules to `shared/`

## Flight-test rule
No autonomy feature advances to the next stage until the previous stage has a reproducible test procedure and logged pass criteria.
