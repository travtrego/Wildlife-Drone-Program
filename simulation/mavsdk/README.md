# PX4 SITL + MAVSDK Bootstrap

This directory implements Issue #4's first software milestone: a repeatable, simulation-only Python mission that connects to PX4 SITL, waits for health, arms, takes off, loiters briefly, and lands.

## What can be prepared in GitHub now

- Python project structure
- MAVSDK smoke-mission code
- configuration and safety guardrails
- unit tests
- CI lint/test workflow
- setup/run documentation

## What still requires a development computer

The repository cannot prove PX4 SITL actually launches until it is run on a compatible development machine. The commands below are therefore a **candidate bootstrap procedure** until the first successful local run is recorded.

Recommended first environment: Ubuntu 24.04 LTS or Ubuntu under WSL2.

## 1. Clone this repository

```bash
git clone https://github.com/travtrego/Wildlife-Drone-Program.git
cd Wildlife-Drone-Program
```

## 2. Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev,sim]"
```

## 3. Install PX4 separately

PX4 itself is intentionally **not vendored into this repository**. Clone the upstream PX4-Autopilot repository and install the dependencies documented by PX4 for the selected host OS.

A typical layout is:

```text
~/src/PX4-Autopilot/
~/src/Wildlife-Drone-Program/
```

## 4. Start an X500-class PX4 SITL vehicle

From the PX4-Autopilot checkout, the first target to validate is:

```bash
make px4_sitl gz_x500
```

PX4 simulator targets change over time. If this target differs in the installed PX4 version, record the working target in this file rather than guessing silently.

## 5. Run the Python smoke mission

In a second terminal:

```bash
cd ~/src/Wildlife-Drone-Program
source .venv/bin/activate
python simulation/mavsdk/smoke_mission.py
```

Expected high-level sequence:

```text
Connecting to PX4 SITL ...
Connected.
Waiting for simulated position/home health ...
Health checks passed.
Arming and taking off ...
Landing ...
PASS: simulated arm -> takeoff -> loiter -> land mission completed.
```

## Safety boundary

`smoke_mission.py` is deliberately simulation-only. Its configuration validator accepts only local UDP port 14540 endpoints. Real-aircraft control will get a separate entry point, separate configuration, and explicit bench/flight validation later.

## Definition of done for Issue #4

Issue #4 is complete only when a fresh development machine can reproduce all of the following and the working versions/commands are committed:

1. PX4 SITL launches successfully.
2. MAVSDK-Python connects to the simulated vehicle.
3. Python reads connection and health telemetry.
4. The simulator completes arm -> takeoff -> loiter -> land.
5. Unit tests and CI pass.
6. The exact host OS, Python version, PX4 revision, simulator target, and MAVSDK version are recorded.

Until that local run happens, this branch is a **software scaffold**, not a flight-proven environment.
