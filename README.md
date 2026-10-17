# Wildlife Drone Program

Aerial robotics research across three aircraft: **X500 V2** for reference testing, **Fighter 2430 VTOL** for endurance mapping, and **Coyote** for permanently equipped wildlife sensing.

Start with [program status](docs/STATUS.md): current evidence, open work and the next gate for each aircraft.

## Find the authoritative record

| Question | Source |
|---|---|
| What is implemented, tested or still pending? | [Program status](docs/STATUS.md) and [validation evidence](docs/VALIDATION.md) |
| What does Coyote have to do? What has been decided? | [Coyote requirements and decisions](coyote/DECISIONS.md) |
| Which parts and mass assumptions are in the model? | [Component ledger](coyote/bom.csv) and [ledger guide](coyote/BOM.md) |
| How were the power/endurance estimates calculated? | [Engineering feasibility](coyote/ENGINEERING_FEASIBILITY.md) |
| Where are detailed geometry, interfaces and history? | [Coyote platform report](coyote/PLATFORM_MASTER_REPORT.md) |
| What does the new desk review propose? | [Review register](coyote/reviews/README.md) |
| How should changes be maintained? | [Documentation ownership](docs/DOCUMENTATION.md) and [development workflow](docs/DEVELOPMENT_WORKFLOW.md) |

## Aircraft

| Platform | Role | Start here |
|---|---|---|
| Holybro X500 V2 | Stock reference aircraft; PX4, MAVSDK and later perception experiments | [X500](x500/README.md) |
| MFE Fighter 2430 | Separate 4+1 lift-and-cruise mapping/surveillance VTOL | [Fighter](fighter_vtol/README.md) |
| Coyote | Six-rotor wildlife research aircraft with permanent full sensor installation | [Coyote](coyote/README.md) |

Flight-critical stabilization, geofencing, battery/link failsafes, return home and pilot override belong to PX4. Companion compute requests mission actions. Planned stack: PX4, QGroundControl, MAVSDK/Python, Jetson, ROS 2 and vision/inference tools. See [architecture](docs/ARCHITECTURE.md).

## Implemented software

The default-branch implementation is a small Python SITL scaffold: configuration validation, an arm/takeoff/loiter/land smoke mission, six configuration tests and lint/compile/unit CI. Platform perception, ROS 2 integration, mission management and real-aircraft autonomy remain planned.

Successful headless simulation runs and stronger telemetry/listener guards are documented in [open PR #6](https://github.com/travtrego/Wildlife-Drone-Program/pull/6). They are not yet part of the default-branch implementation. [Validation evidence](docs/VALIDATION.md) records the exact revision and limits.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev,sim]"
pytest
```

For simulator setup and the distinction between the scaffold and validated branch, use the [MAVSDK guide](simulation/mavsdk/README.md).

Promote software through lint -> unit tests -> SITL -> props-off bench -> controlled reference flight -> logged review -> release. Reusable modules belong in `shared/` after appropriate validation; aircraft-specific work stays in its aircraft directory. Raw flight logs, large media, datasets, model binaries and credentials stay outside Git; retain evidence manifests and summaries.
