# Claude independent Coyote engineering review request

**Structured review brief.** A supplied October 15 desk review is now registered in [reviews/README.md](reviews/README.md). Its exact input revision and claims are not independently verified; proposals remain pending. This brief is retained for a structured engineering audit.

## Review objective

Act as an independent skeptical UAV systems engineer reviewing **Coyote only**, the permanently equipped **EFT E616P hexacopter** wildlife research aircraft. Do not conflate it with the Fighter VTOL or X500 training quad. The owner wants **all planned sensors installed at once**, not modular mission swaps.

Read these before answering:
0. [Requirements and decisions](DECISIONS.md), [ledger guide](BOM.md) and [review register](reviews/README.md)
1. [Platform Master Report](PLATFORM_MASTER_REPORT.md)
2. [Engineering Feasibility](ENGINEERING_FEASIBILITY.md)
3. [Coyote README](README.md)
4. [Program Architecture](../docs/ARCHITECTURE.md)
5. [GitHub issue #3](https://github.com/travtrego/Wildlife-Drone-Program/issues/3)

## Required independent findings

Analyze, do not simply agree with earlier recommendations:
- **Optics and sensing:** Is ILX-LR1 + *original SEL70200G* + T7 the best feasible fixed camera stack for mammal/bird identification without inappropriate approach distances? Can it balance? Is in-flight zoom realizable? What independent lens/camera/gimbal confirmation is required? Are the thermal, LiDAR, and stereo components appropriate for wildlife vs industrial robotics?
- **Physical integration:** E616P revision-specific physical drawings, frame shell volume, landing legs, fixed mounts, all gimbal axes, rotor/mast occlusion, airflow, CG and vibration; classify as measured/unknown.
- **BOM completeness:** Find missing structural, safety, electrical or recording components. Audit 16.609kg catalogue subtotal, 3.750kg placeholders, 23.780kg 22Ah scenario and exclusions/double counts.
- **Power/endurance:** Independently recompute hover thrust interpolation from the Hobbywing published power table, battery Wh, propulsion load, power conversion losses, current C-rating, wind/heat margins and safe reserve; reconcile modeled 22/26/33/36Ah cases. Propose credible verification tests. No claimed 25–30min unless demonstrated.
- **Reliability and autonomy:** Flight controller separate from Jetson; telemetry redundancy, data synchronization, sensor bandwidth, failure modes, safety envelope, interference and failsafes.
- **Operational viability:** 55lb takeoff rules (jurisdiction-dependent), wildlife disturbance, weather/environmental ratings, pilot/operator requirements.
- **Value-for-complexity:** Call out components adding cost/weight without adequate science capability; suggest optimized replacements ONLY if all owner-required sensor capabilities remain permanently installed and the constraints are preserved.

## Response format

1. **Verdict**: viable / conditional / not viable, with confidence.
2. **Critical blockers**: table of risk, evidence/reference, impact, remedy and required proof.
3. **Corrected mass and energy ledger**, with assumptions written out and reproducible calculations (not false precision).
4. **Camera and payload geometry**: specific mounting dimensions still missing, expected FOV collisions.
5. **Questions for EFT / Gremsy / Sony / Hobbywing and battery vendors**: concrete question list and drawing/spec required.
6. **Action plan:** next 3–5 engineering actions ranked by impact on purchase readiness.
7. **Suggested edits to docs and GitHub issue #3**; do not apply them without owner approval.

## Ground rules
- Do not claim contact with manufacturers, tests, permissions, hardware ownership or validated fit without evidence.
- Cite primary manufacturer documentation and the inspected exact version, including dated URL, if available.
- Preserve the **non-swappable permanent payload** decision.
- The E616P is selected as the current design **candidate**; do not approve its purchase prematurely.
- Separate factual corrections from optional alternatives or decisions requiring the owner's agreement.
