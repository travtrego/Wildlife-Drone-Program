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
1. Mechanical inspection and assembly
2. Props-off avionics integration
3. PX4 configuration
4. Manual/reference flight
5. QGroundControl logging and review
6. MAVSDK Python takeoff / land / waypoint experiments
7. Jetson integration
8. ROS 2 integration
9. Camera / perception experiments
10. Perception-driven mission behaviors
11. Promote stable modules to `shared/`

## Flight-test rule
No autonomy feature advances to the next stage until the previous stage has a reproducible test procedure and logged pass criteria.
