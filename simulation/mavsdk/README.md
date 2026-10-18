# PX4 SITL + MAVSDK

This is Issue #4's simulation-only smoke mission: connect, wait for position/home health, arm, take off, verify airborne state and altitude, loiter, and land.

The headless X500 workflow was executed successfully on 2026-09-03. See the [validation record](../../docs/SITL_VALIDATION_2026-09-03.md) for exact versions, commands, logs, and limits. Neither a real aircraft nor the Gazebo GUI was validated.

## How the pieces fit

~~~text
Python mission -> MAVSDK Python -> local MAVSDK server -> MAVLink/UDP -> PX4 SITL
                                                                        <-> Gazebo X500
~~~

Python requests mission-level actions. PX4 estimates state, performs health/arming checks, and controls flight. Gazebo simulates physics and sensors. MAVSDK's takeoff action acknowledges a command; it does not mean the climb has finished. The mission waits for airborne telemetry and at least 90% of the requested relative altitude before starting its timed loiter.

## 1. Prepare Ubuntu

Validated host: Windows 11 Pro 25H2, Ubuntu 24.04.4 in WSL2. Follow the [official PX4 WSL guide](https://docs.px4.io/main/en/dev_setup/dev_env_windows_wsl) if Ubuntu is not installed. A Windows feature result of 3010 means a restart is required, not that Ubuntu or PX4 is ready.

Keep PX4 source/build files inside the Linux filesystem, not under /mnt/c.

~~~bash
sudo apt-get update
sudo apt-get install -y python3-venv
mkdir -p ~/src
cd ~/src
~~~

The python3-venv package was required on the fresh Ubuntu installation; without it, venv creation failed because ensurepip was unavailable.

## 2. Clone the project and test first

~~~bash
git clone https://github.com/travtrego/Wildlife-Drone-Program.git
cd Wildlife-Drone-Program
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,sim]" -c simulation/mavsdk/constraints-validated.txt
ruff check shared simulation tests
python -m compileall -q shared simulation
pytest
deactivate
~~~

While the validation PR is open, check out branch feat/issue-4-sitl-validation before creating the environment. The constraints file pins the three tested top-level tools; it is not a full transitive dependency lock. Unit tests do not require MAVSDK or a simulator, so CI installs only the dev extra.

## 3. Install PX4 separately

PX4 is not vendored into this repository. The tested revision is 6041c961dd619b08f9a726a4052b1fadf1f98e94. To recreate that source state:

~~~bash
cd ~/src
git clone --recursive https://github.com/PX4/PX4-Autopilot.git
cd PX4-Autopilot
git checkout 6041c961dd619b08f9a726a4052b1fadf1f98e94
git submodule update --init --recursive
sudo bash Tools/setup/ubuntu.sh --no-nuttx
~~~

The official script installs Gazebo Harmonic and PX4 build dependencies. The --no-nuttx flag skips the embedded-hardware toolchain. On Ubuntu's Python 3.12, the script uses --break-system-packages for PX4's build-time Python dependencies; mission dependencies remain in their own venv. A dedicated development WSL distribution isolates this system change from other Linux projects.

The actual first run used a shallow recursive clone, which caused git describe to print a missing-tag warning and PX4 to label itself v0.0.0. The full commit above remains authoritative; the build succeeded without fetching tags or modifying PX4 source.

## 4. Start the X500 simulation

In terminal 1, outside the project virtual environment:

~~~bash
cd ~/src/PX4-Autopilot
HEADLESS=1 make px4_sitl gz_x500
~~~

Wait for "Gazebo world is ready", "world: default, model: x500_0", and "Startup script returned successfully". Initial GCS warnings may appear before the client connects. Do not disable arming checks to hide a persistent failure.

The [official Gazebo guide](https://docs.px4.io/main/en/sim_gazebo_gz/) describes headless mode. It removes the GUI, not the simulated physics or sensors. Omitting HEADLESS=1 should open the GUI, but that path was not tested here.

## 5. Run the mission

In terminal 2:

~~~bash
cd ~/src/Wildlife-Drone-Program
source .venv/bin/activate
python simulation/mavsdk/smoke_mission.py
~~~

Observed output from the strengthened mission:

~~~text
Connecting to PX4 SITL at udpin://127.0.0.1:14540 ...
Connected.
Waiting for simulated position/home health ...
Health checks passed.
Arming and taking off to 3.0 m ...
Airborne at 2.7 m; loitering for 5.0 s ...
Landing ...
PASS: simulated arm -> takeoff -> loiter -> land mission completed.
~~~

PX4 independently logged external arming, takeoff detected, landing detected, and disarmed by landing. The 2.7 m line is the 90% climb threshold, not a claim that exactly 3.0 m was measured. Loiter means a timed pause after takeoff while PX4 holds position, not an uploaded waypoint mission.

## 6. Stop and retain evidence

After landing/disarm, press Ctrl+C in terminal 1 to stop PX4 and Gazebo together. Typing shutdown in the PX4 shell alone left Gazebo running during the first validation; Ctrl+C stopped the wrapper and remaining child process.

PX4 ULogs are under build/px4_sitl_default/rootfs/log/. They are intentionally ignored by this repository. Keep local logs and record paths/checksums rather than committing large binaries.

## Safety and validation limits

- Default listener: udpin://127.0.0.1:14540, loopback only. [MAVSDK v3 connection syntax](https://mavsdk.mavlink.io/main/en/cpp/api_changes.html) makes listener direction explicit.
- Remote addresses, blank/wildcard listeners, serial endpoints, and other ports are rejected. Legacy udp:// is accepted only with explicit loopback hosts for compatibility.
- Do not connect hardware, run a MAVLink hardware bridge, or forward a real aircraft into this endpoint. Loopback cannot identify the source behind a manually configured bridge.
- Health readiness requires simulated global position and home position. PX4 still decides whether arming is permitted.
- Telemetry gates have timeouts and reject ended streams. A mission error is not PASS; inspect the simulator before retrying or stopping it.
- This validates one headless X500 configuration on one laptop, not GUI rendering, ROS 2, hardware, bench tests, real flight, fault injection, or a second fresh machine.
