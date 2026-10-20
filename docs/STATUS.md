# Program status

Last reconciled: **2026-10-18** after PRs #6, #7 and #8 merged. This page is a dated status snapshot; issue and PR state can change.

| Workstream | Established evidence | Next gate | Tracker |
|---|---|---|---|
| X500 hardware | Stock hardware baseline and staged plan; no completed hardware acceptance record in this repo | Inventory, assembly, props-off avionics, then repeatable manual/reference flights and logs | [#1](https://github.com/travtrego/Wildlife-Drone-Program/issues/1) |
| Fighter hardware | Candidate 4+1 architecture; measurements not recorded | Exact revision, bare mass, mounts, prop/bay clearances and CG before propulsion freeze | [#2](https://github.com/travtrego/Wildlife-Drone-Program/issues/2) |
| Coyote | Requirements, owner decisions of 2026-10-18, candidate architecture and preliminary feasibility study (pre-decision configuration) | **Procurement HOLD:** revision-specific geometry, full installed mass/CG, optics, power/current and endurance evidence | [#3](https://github.com/travtrego/Wildlife-Drone-Program/issues/3) |
| Python/SITL | PRs #5 and #6 merged: loopback-only listener, telemetry gates, recorded headless X500 SITL runs and CI | Second independently provisioned machine still unproven | [#4](https://github.com/travtrego/Wildlife-Drone-Program/issues/4), [#6](https://github.com/travtrego/Wildlife-Drone-Program/pull/6) |
| Coyote companion action gate | PR #8 merged: unit-tested request gate (no MAVSDK wiring) | MAVSDK adapter with ground-station delegation (R6), then SITL fault tests | [#8](https://github.com/travtrego/Wildlife-Drone-Program/pull/8) |
| Perception / ROS 2 / shared mission system | Architecture and planned modules only | Reproducible basic simulation path before adding integration | [Architecture](ARCHITECTURE.md) |

## What the simulation result establishes

Three successful headless X500 SITL runs are recorded from PR #6 (now merged), including a clean checkout/new virtual environment on the same laptop. This is not hardware, real flight or a second fresh-machine reproduction. See [validation evidence](VALIDATION.md).

## Coyote decisions awaiting evidence or owner choice

Use [DECISIONS.md](../coyote/DECISIONS.md) for requirements, candidate status, procurement gates and pending alternatives. The owner made dispositions on its proposals on 2026-10-18; the feasibility tables and `bom.csv` still describe the earlier October 15 configuration until recalculated. See [review register](../coyote/reviews/README.md).

## Update rule

Update this page when a stage changes, citing the relevant revision and evidence. Do not check off a hardware milestone from a plan, a vendor specification or a successful CI run. Keep detailed calculations and requirements in their authoritative files rather than copying them here.
