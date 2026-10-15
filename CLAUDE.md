# CLAUDE.md — Wildlife Drone Program

This is the repository-level handoff for Claude Code and other development agents. **Read before making project changes.**

## Scope and source of truth
There are three distinct aircraft:
- `x500/` — Holybro X500 V2 reference aircraft, flight control and autonomy teaching/test platform.
- `fighter_vtol/` — Makeflyeasy Fighter 2430 4+1 VTOL, separate fixed-wing endurance mapping project.
- `coyote/` — premium **EFT E616P candidate hexacopter** for fixed-payload close-range wildlife sensing and autonomous research.

**For work on Coyote, first read (in this order):**
1. [`coyote/PLATFORM_MASTER_REPORT.md`](coyote/PLATFORM_MASTER_REPORT.md) — consolidated owner's requirements, historical decisions, current baseline and Claude review brief.
2. [`coyote/ENGINEERING_FEASIBILITY.md`](coyote/ENGINEERING_FEASIBILITY.md) — itemized prototype mass, power, gimbal compatibility, battery and endurance estimates.
3. [`coyote/README.md`](coyote/README.md) — shorter maintained Coyote architecture.
4. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — cross-aircraft autonomy/safety hierarchy.
5. [`coyote/CLAUDE_REVIEW_REQUEST.md`](coyote/CLAUDE_REVIEW_REQUEST.md) — scoped independent engineering audit request.

## Non-negotiable owner design requirements for Coyote
- Coyote is a **six-rotor hexacopter**, with **EFT E616P** preferred pending fit/performance validation, not a VTOL and not the X500.
- **All sensing hardware is permanently installed. NO payload or sensor swaps by mission.** Sensors may be electronically selected as needed; hardware remains installed.
- Keep the research suite: Sony high-resolution RGB + telephoto stabilized mount, fixed thermal, OAK-D Pro W short-range vision, JT128-class 3D LiDAR, RTK GNSS, Jetson Orin NX-class perception computer and Pixhawk 6X-class safety autopilot.
- Optimize for **wildlife observation, identification, 3D mapping and AI autonomy** with ~25–30 minute *target*, but never claim target met without evidence.
- Jetson handles perception / mission decisions. **Pixhawk/PX4 must retain flight-critical safety and pilot override.**
- Maintain FAA and local wildlife/animal-disturbance/legal considerations, especially the ~55lb small-UAS threshold.

## Truth and engineering discipline
- Distinguish **owner requirements**, **selected engineering candidates**, **illustrative budget values**, **vendor specifications**, **tested/verified facts**, and **unknowns**.
- The proposed **ILX-LR1 + original SEL70200G 70–200 F4 + Gremsy T7** has *not* been proven to balance/fit or support zoom/camera interfacing. Gimbal mass rating is not a fit certificate.
- Six Hobbywing X8s, Tattu 12S example packs, 120W non-prop allowance and 80%-usable-energy assumption are **model inputs, not approved purchases**.
- Existing time figures (~20–29min) are simplified screening values, **not safe usable endurance**.
- Manufacturer E616P dimensions reported by different listings vary. Require SKU/revision-specific drawing and measure bay/mast/gimbal/landing gear clearance.
- Do not silently resolve payload overload by removing sensors or reverting to mission-interchangeable equipment.
- Do not write “approved,” “fits,” “validated,” “bought,” “field-tested,” “Claude reviewed,” or “ready to fly” unless specific evidence exists.
- Do not request or expose secrets; do not change source files or issue status without review / owner authorization.
- When proposing changes, explain architecture, tradeoffs, testing, source links and evidence that would prove the change.

## Review workflow
1. Read all Coyote docs and issue [#3](https://github.com/travtrego/Wildlife-Drone-Program/issues/3).
2. Independently check manufacturer documentation, arithmetic, geometry and missing components.
3. Return issues ranked by severity, with **evidence / uncertainty / proposed fix / acceptance test**.
4. Keep unresolved specifications and open procurement gates visible.
5. Update the master report and relevant issues only after the user approves a change.
