# Program status

Last reconciled: **2026-10-17** against main `4ded919`, open issues and PR #6. This page is a dated status snapshot; issue and PR state can change.

| Workstream | Established evidence | Next gate | Tracker |
|---|---|---|---|
| X500 hardware | Stock hardware baseline and staged plan; no completed hardware acceptance record in this repo | Inventory, assembly, props-off avionics, then repeatable manual/reference flights and logs | [#1](https://github.com/travtrego/Wildlife-Drone-Program/issues/1) |
| Fighter hardware | Candidate 4+1 architecture; measurements not recorded | Exact revision, bare mass, mounts, prop/bay clearances and CG before propulsion freeze | [#2](https://github.com/travtrego/Wildlife-Drone-Program/issues/2) |
| Coyote | Requirements, candidate architecture and preliminary feasibility study | **Procurement HOLD:** revision-specific geometry, full installed mass/CG, optics, power/current and endurance evidence | [#3](https://github.com/travtrego/Wildlife-Drone-Program/issues/3) |
| Python/SITL scaffold | PR #5 merged; six configuration tests and CI workflow on default branch | Review stronger implementation and recorded runtime evidence in PR #6 | [#4](https://github.com/travtrego/Wildlife-Drone-Program/issues/4), [#6](https://github.com/travtrego/Wildlife-Drone-Program/pull/6) |
| Perception / ROS 2 / shared mission system | Architecture and planned modules only | Reproducible basic simulation path before adding integration | [Architecture](ARCHITECTURE.md) |

## What the simulation result establishes

Three successful headless X500 SITL runs are recorded in PR #6, including a clean checkout/new virtual environment on the same laptop. Stronger runtime code, 13 tests and exact versions are on that open branch. This is not hardware, real flight or a second fresh-machine reproduction. See [validation evidence](VALIDATION.md).

## Coyote decisions awaiting evidence or owner choice

Use [DECISIONS.md](../coyote/DECISIONS.md) for requirements, candidate status, procurement gates and pending alternatives. A supplied October 15 desk review is now registered; receiving that artifact does not approve its hardware substitutions or endurance-target change. See [review register](../coyote/reviews/README.md).

## Update rule

Update this page when a stage changes, citing the relevant revision and evidence. Do not check off a hardware milestone from a plan, a vendor specification or a successful CI run. Keep detailed calculations and requirements in their authoritative files rather than copying them here.
