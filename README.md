# Wildlife Drone Program

A modular autonomy and aerial robotics program spanning three aircraft roles:

- **X500 V2** — reference and learning platform for PX4, MAVSDK, ROS 2, perception, and autonomy validation.
- **Fighter 2430 VTOL** — long-endurance mapping and surveillance platform.
- **Coyote** — advanced close-range autonomous sensing and multi-sensor robotics platform.

## Program philosophy

1. Prove simple behaviors before complex behaviors.
2. Keep flight-critical control on the autopilot.
3. Keep AI and higher-level mission logic on the companion computer.
4. Promote only validated software into shared modules.
5. Treat flight logs and test evidence as engineering artifacts, not anecdotes.
6. Keep each aircraft mission-focused rather than forcing one platform to do everything.

## Repository layout

```text
Wildlife-Drone-Program/
├── docs/            # Architecture, procedures, design records, test plans
├── shared/          # Reusable autonomy, telemetry, safety, logging, messages
├── x500/            # X500-specific configs, scripts, vision, and flight tests
├── fighter_vtol/    # Mapping/surveillance VTOL software and configuration
├── coyote/          # Perception, sensor fusion, autonomy, and platform configs
├── simulation/      # SITL, scenarios, synthetic tests
└── tests/           # Shared automated tests and validation utilities
```

## Software progression

**X500 → shared autonomy stack → Fighter VTOL / Coyote**

The X500 is the primary proving ground. Modules that survive simulation, bench testing, and flight validation can be promoted into `shared/` and reused by the larger aircraft.

## Initial technology stack

- PX4
- MAVSDK
- Python
- ROS 2
- Jetson companion compute
- OpenCV / AI inference tooling
- QGroundControl

## Safety architecture

The companion computer may request mission-level actions, but the autopilot retains hard authority over geofencing, flight stabilization, return-to-home, battery failsafes, link-loss behavior, and other safety-critical constraints.

## Current status

Repository scaffold initialized. Hardware-specific code will be added as each platform reaches its integration stage.
