# Issue #4: local SITL validation, 2026-09-03

## Scope and baseline

PR #5 was already merged as 2054580bc2fa21cf3b68480fcc7831828588e58c. No scaffold was duplicated. Work continued on feat/issue-4-sitl-validation.

The original mission and then the strengthened mission completed in headless PX4/Gazebo X500 SITL on this laptop. No real aircraft was connected or commanded. No PX4 source or arming/failsafe parameter was changed to obtain a pass.

## Exact observed environment

| Component | Observed value |
| --- | --- |
| Windows | Microsoft Windows 11 Pro, 25H2, 10.0.26200.9278 |
| WSL | 2.7.12.0, distribution version 2 |
| WSL kernel | 6.18.33.2-microsoft-standard-WSL2 (WSL package: 6.18.33.2-2) |
| WSLg | 1.0.73.2 (GUI not tested) |
| Ubuntu | 24.04.4 LTS (Noble Numbat), x86_64 |
| Linux Python | 3.12.3 |
| Windows baseline Python | 3.12.10 |
| MAVSDK-Python | 3.17.2 |
| pytest | 8.4.2 |
| Ruff | Linux 0.16.6; Windows baseline 0.16.5 |
| PX4 commit | 6041c961dd619b08f9a726a4052b1fadf1f98e94 |
| PX4 Gazebo models submodule | bb0b9cf974acf4f1bcb5f5fcf80b88841562dea9 |
| Simulator | Gazebo Harmonic, gz-sim 8.15.0 |
| Target / world / instance | gz_x500 / default / x500_0; SYS_AUTOSTART=4001 |
| CMake / GCC | 3.28.3 / 13.3.0 |
| Final client endpoint | udpin://127.0.0.1:14540 |
| Mission | 3.0 m requested altitude; 5.0 s loiter; 30 s connection / 60 s health timeout |

## Setup commands actually executed

Ubuntu was initialized as user travt after the Windows/WSL prerequisite restart. Source was placed in the Linux filesystem.

~~~bash
cd ~/src
git clone https://github.com/travtrego/Wildlife-Drone-Program.git
cd Wildlife-Drone-Program
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,sim]"
ruff check shared simulation tests
python -m compileall -q shared simulation
pytest
~~~

The first venv attempt required installing python3-venv with apt. The baseline then passed Ruff, compileall, and all 6 original tests on Windows and Ubuntu before PX4 was built.

~~~bash
cd ~/src
git clone --recursive --shallow-submodules --depth 1 https://github.com/PX4/PX4-Autopilot.git
cd PX4-Autopilot
git rev-parse HEAD
~~~

From PowerShell, the official setup script was executed as WSL root without storing or passing a password:

~~~powershell
wsl.exe -d Ubuntu-24.04 -u root -- bash -lc 'cd /home/travt/src/PX4-Autopilot && DEBIAN_FRONTEND=noninteractive bash Tools/setup/ubuntu.sh --no-nuttx'
~~~

The setup script exited 0, installing PX4 build dependencies and Gazebo Harmonic while skipping NuttX. First build/run:

~~~bash
cd ~/src/PX4-Autopilot
HEADLESS=1 make px4_sitl gz_x500
~~~

PX4 built successfully, Gazebo reported world ready and spawned x500_0, and the startup script returned successfully. PX4 explicitly reported MAVLink only on localhost. Its onboard link used local UDP 14580 and remote port 14540.

## Observed live runs

### 1. Unmodified main-branch mission

~~~bash
cd ~/src/Wildlife-Drone-Program
.venv/bin/python simulation/mavsdk/smoke_mission.py
~~~

Exit 0. Connection, position/home health, arm, takeoff, and land completed. MAVSDK emitted a deprecation warning for udp://:14540. PX4 independently logged partner IP 127.0.0.1, readiness, external arming, takeoff detected, landing detected, and disarmed by landing.

The original code slept immediately after the takeoff command, so its interval did not separately prove completion of the climb before loiter. This motivated the altitude gate in run 2.

### 2. Strengthened feature-branch mission

The feature-branch source was in the Windows checkout; the Linux venv supplied MAVSDK. PYTHONPATH explicitly selected the modified shared module instead of the older editable Linux clone:

~~~bash
cd /mnt/c/Users/travt/Documents/Codex/2026-09-02/referenced-chatgpt-conversation-this-is-an/work/Wildlife-Drone-Program
PYTHONPATH=. /home/travt/src/Wildlife-Drone-Program/.venv/bin/python simulation/mavsdk/smoke_mission.py
~~~

Exit 0 with no deprecated-URL warning:

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

PX4 independently logged the same arming, takeoff, landing, and disarm transitions. The climb gate is 90% of target; this does not claim an exact 3.0 m measurement. The timed loiter began only after that gate.

### 3. Clean-checkout reproduction

Cloned committed revision b0447a73924547c7fe2daa05f9034b1ee47756d8 into a new Linux directory and created a new venv. This reused the installed Ubuntu/PX4/Gazebo prerequisites and the existing PX4 build; it was not a second physical machine or a clean OS reinstall.

~~~bash
cd ~/src
git clone --single-branch --branch feat/issue-4-sitl-validation https://github.com/travtrego/Wildlife-Drone-Program.git Wildlife-Drone-Program-issue4-clean
cd Wildlife-Drone-Program-issue4-clean
git rev-parse HEAD
git status --short
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,sim]" -c simulation/mavsdk/constraints-validated.txt
.venv/bin/ruff check shared simulation tests
.venv/bin/python -m compileall -q shared simulation
.venv/bin/pytest
~~~

All checks passed; pytest reported 13 passed in 0.08 s. The fresh venv installed MAVSDK 3.17.2, pytest 8.4.2, and Ruff 0.16.6. After restarting the same HEADLESS=1 X500 target:

~~~bash
cd ~/src/Wildlife-Drone-Program-issue4-clean
.venv/bin/python simulation/mavsdk/smoke_mission.py
git status --short
~~~

The mission exited 0 with the same output as run 2, including airborne at 2.7 m and 5.0 s loiter. PX4 independently confirmed external arming, takeoff, landing, and disarm. The checkout remained clean. Ctrl+C stopped the simulator, and process inspection confirmed no PX4/Gazebo process remained. The subsequent documentation-only commit does not change the runtime code tested here.

### Local ULog evidence

Base directory: /home/travt/src/PX4-Autopilot/build/px4_sitl_default/rootfs/log/2026-09-03/

| Run | Filename | SHA-256 |
| --- | --- | --- |
| Original | 18_29_58.ulg | 8a2fd4f178450eb26b99774f7c5e9c3d6df8b39868d28879f54695f807b2869b |
| Strengthened | 18_34_27.ulg | 67d12f478f623c2bf2a2f7a9146c82ebf5071d81ea2e6c37a0a835acfd9d67ce |
| Clean checkout | 18_47_39.ulg | 01ddb34f3b32a19cdbc535454782395c96c894ba3cda8a066c505f10d07bf417 |

Filenames are recorded as produced by PX4; no timezone inference is made from them. Binary logs remain local and ignored by Git.

## Fixes and checks

- Installed python3-venv after the missing-ensurepip failure.
- Ignored editable-install packaging metadata with *.egg-info/.
- Changed the default to MAVSDK v3's explicit loopback listener and raised the minimum MAVSDK major version to 3.
- Rejected blank/wildcard listeners, which can accept traffic on non-loopback interfaces. Explicit legacy loopback URLs remain compatible.
- Added airborne and relative-altitude gates before loiter; ended telemetry streams fail instead of silently succeeding.
- Added 7 focused telemetry tests (13 total) and explicit pytest repository-root import configuration.
- Ruff, compileall, and 13 tests passed on Windows and Ubuntu. Ubuntu tests against the Windows-mounted checkout used -p no:cacheprovider after an optional cache permission warning.
- The missing-tag/v0.0.0 warning came from the shallow PX4 clone; the full commit SHA is authoritative.
- SDF gz_frame_id warnings and initial missing-GCS warnings did not prevent successful runs. No health check was disabled.
- PX4 shutdown alone left Gazebo running; Ctrl+C in the launching terminal stopped the remaining processes. Inspection confirmed no PX4/Gazebo process remained after run 2.

## Remaining validation boundary

Clean-checkout reproduction is verified above. GitHub Actions results are tracked on the accompanying validation PR, separately from this local runtime evidence. This does not claim a second fresh machine, Gazebo GUI rendering, ROS 2, bench tests, real aircraft, or real flight. Unit tests and CI are not substitutes for SITL evidence.
