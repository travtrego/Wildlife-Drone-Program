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

## Software — unit-test stage only

[`flight/waypoint_mission.py`](flight/waypoint_mission.py) is the first piece of the multirotor flight layer: it refuses (never clips) waypoint lists outside advisory limits, converts north/east/altitude-above-home waypoints to global items, and verifies a mission by uploading it, downloading it back from PX4 and comparing count, order, position, altitude, speed and fly-through for every item. It never arms, starts a mission or commands flight. The code is aircraft-agnostic; X500 numbers live in [`flight/settings.py`](flight/settings.py) as **model inputs / SITL development placeholders** (30 m ceiling, 3 m floor, 100 m radius, 5 m/s, 20 waypoints), which must sit inside the PX4 geofence and failsafe parameters. It stays here, not in `shared/`, until SITL evidence exists (shared-code rule).

[`simulation/mavsdk/waypoint_upload_check.py`](../simulation/mavsdk/waypoint_upload_check.py) runs that upload/read-back check against loopback PX4 SITL only (same endpoint guard as the smoke mission), from the repository root:

~~~bash
python -m simulation.mavsdk.waypoint_upload_check  # PX4 SITL gz_x500 must already be running
~~~

**Evidence status:** unit tests with fake MAVSDK objects (`tests/test_x500_waypoint_mission.py`); conversion also checked against the MAVSDK-Python 3.17.2 `MissionItem`/protobuf classes without a vehicle. **Not yet run against PX4 SITL**, so the read-back tolerances and how PX4/MAVSDK return speed and fly-through on download are unobserved. No mission has been flown in SITL or on hardware.
