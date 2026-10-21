# Program Architecture

## Platform roles

### X500 V2 — reference / learning platform
Purpose: establish the common multirotor flight layer (PX4 control, waypoint missions, telemetry and safety guards) on a low-complexity quad before promoting code to larger aircraft.

Scope (owner decision 2026-10-21): waypoint autonomy only. No Jetson, perception or AI mission logic on the X500; those are developed for Coyote.

Primary progression:
1. Stock PX4 flight
2. QGroundControl setup and logging
3. MAVSDK Python control
4. Telemetry and mission scripts
5. Autonomous waypoint missions
6. Promotion of validated flight-layer modules into `shared/` for Coyote reuse

### Fighter 2430 VTOL — mapping / surveillance
Purpose: long-endurance, wide-area mapping and surveillance using the shared autonomy stack while keeping VTOL/fixed-wing flight control on PX4.

Working architecture:
- 4+1 lift-and-cruise VTOL
- 12S power architecture
- Pixhawk 6X Pro class autopilot
- Jetson Orin NX class companion computer
- dual-antenna RTK GNSS
- airspeed sensing
- modular mapping / multispectral / EO-IR payloads

### Coyote — advanced close-range sensing robot
Purpose: close-range autonomous sensing, inspection, wildlife observation, and multi-sensor perception.

Working architecture:
- industrial multirotor platform
- Pixhawk flight controller
- Jetson companion compute
- RGB, thermal, depth, and LiDAR-class sensing
- high-bandwidth data link
- richer local perception and sensor fusion than the VTOL

## Control hierarchy

```text
Mission objective / operator
          |
          v
Companion computer (Python / ROS 2 / AI)
          |
          v
PX4 autopilot
          |
          v
Motors / servos / actuators
```

The companion computer decides *what* mission action to request. PX4 decides *how* to fly the aircraft safely.

## Shared-code rule

Platform-specific code starts inside the relevant aircraft folder. A module should move to `shared/` only after its interface is stable and it has passed the appropriate simulation, bench, and flight tests.

## Safety boundary

The AI/autonomy layer must not bypass hard safety constraints enforced by the autopilot. Geofence, stabilization, battery failsafes, return-to-home, link-loss behavior, and manual override remain outside the authority of experimental AI mission logic.
