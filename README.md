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
├── .github/         # Continuous-integration workflows
├── docs/            # Architecture, procedures, design records, test plans
├── shared/          # Reusable autonomy, telemetry, safety, logging, messages
├── x500/            # X500-specific configs, scripts, vision, and flight tests
├── fighter_vtol/    # Mapping/surveillance VTOL software and configuration
├── coyote/          # Perception, sensor fusion, autonomy, and platform configs
├── simulation/      # SITL, scenarios, synthetic tests
└── tests/           # Shared automated tests and validation utilities
```

## Software progression

**X500 -> shared autonomy stack -> Fighter VTOL / Coyote**

The X500 is the primary proving ground. Modules that survive simulation, bench testing, and flight validation can be promoted into `shared/` and reused by the larger aircraft.

## Initial technology stack

- PX4
- MAVSDK
- Python
- ROS 2
- Jetson companion compute
- OpenCV / AI inference tooling
- QGroundControl

## First software milestone: Issue #4

The PX4 SITL + MAVSDK development path includes:

- a Python project definition (`pyproject.toml`)
- a simulation-only MAVSDK arm/takeoff/loiter/land smoke mission
- local-SITL connection guardrails
- unit tests for configuration, safety checks, and telemetry gates
- GitHub Actions lint/test automation
- a reproducible local setup procedure

See [`simulation/mavsdk/README.md`](simulation/mavsdk/README.md) for setup and run instructions.

On 2026-09-03, the X500-class headless simulation successfully connected, passed position/home health checks, armed, took off, loitered, landed, and disarmed on Ubuntu 24.04.4 under WSL2. Exact versions, commands, observed output, and validation limits are recorded in [`docs/SITL_VALIDATION_2026-09-03.md`](docs/SITL_VALIDATION_2026-09-03.md). This is **simulation evidence only**, not hardware or real-flight validation.

## Local Python quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev,sim]"
pytest
```

## Safety architecture

The companion computer may request mission-level actions, but the autopilot retains hard authority over geofencing, flight stabilization, return-to-home, battery failsafes, link-loss behavior, and other safety-critical constraints.

The first MAVSDK smoke mission is intentionally **SITL-only** and binds to `127.0.0.1:14540`. It rejects remote addresses, wildcard listeners, and other ports. Do not forward a real aircraft into this loopback endpoint. Real-aircraft command code will be introduced through a separate, explicitly validated path.

## Development workflow

Use short-lived feature branches and promote changes through the validation ladder:

**lint -> unit test -> SITL -> bench test -> controlled reference flight -> logged review -> release tag**

See [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md).

## Current status

The first PX4/MAVSDK simulation has been executed successfully. Hardware-specific flight code will be added only as each platform reaches its integration and validation stage; no hardware validation is claimed.
