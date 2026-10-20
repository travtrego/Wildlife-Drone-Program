# Fighter 2430 VTOL

## Role
Dedicated long-endurance mapping and surveillance aircraft. It is not the close-range Coyote platform.

## Current engineering baseline
- MFE Fighter 2430 KIT
- 4+1 lift-and-cruise layout
- 12S architecture
- lift candidate: 4x V505 KV260
- preferred lift prop: 16x5.4, primarily for thermal/current margin
- 60A 12S-capable FOC ESC class
- cruise candidate: AT4130 KV230
- folding FS15x8-class cruise prop
- AT115A-class cruise ESC
- battery target: 12S 20-22 Ah, pending measured mass and CG
- Pixhawk 6X Pro class autopilot
- Jetson Orin NX 16 GB class companion computer
- external 12S-compatible UBEC for Jetson/baseboard
- dual-antenna RTK GNSS + airspeed sensor

## Payload philosophy
Use mission-specific swappable payloads rather than carrying every sensor simultaneously.

Candidate modules:
- Sony ILX-LR1 high-resolution RGB mapping
- MicaSense Altum-PT multispectral / thermal science mapping
- stabilized EO/IR surveillance module
- lightweight mapping LiDAR only if a mission requires canopy/bare-earth/3D structure work

## Stage 1 on airframe arrival
Before freezing propulsion:
1. identify exact airframe revision
2. assemble bare airframe
3. weigh it
4. measure motor mounts
5. measure prop clearance
6. confirm payload bay dimensions
7. record empty CG and manufacturer CG range
8. reconcile actual mass with conservative MTOW/payload assumptions

The delivered hardware and measured aircraft take precedence over conflicting reseller specifications.

## Software — unit-test stage only

[`mission/survey_plan.py`](mission/survey_plan.py) turns a rectangular survey area into a deterministic, ordered list of *proposed* mission items: VTOL takeoff at home, transition to fixed-wing, survey lines with one-turn-radius lead-in/run-out, an inbound approach, back-transition and VTOL landing at home. It sends nothing; PX4 keeps transitions, fixed-wing guidance, geofence, failsafes, RTL and pilot override.

The planner rejects a plan instead of tightening it when:
- a 180-degree turn between consecutive lines would be narrower than twice the modeled turn radius (tight spacing is first handled by interleaving lines 0, g, 2g, …, then 1, 1+g, …);
- the first line is too close to home for the modeled forward transition plus alignment;
- any fixed-wing point, padded by one turn radius, leaves the advisory distance from home;
- altitudes leave the advisory band (survey and transition at or above the fixed-wing floor, at most 120 m).

**Evidence status:** unit tests only (`tests/test_fighter_survey_plan.py`). Not wired to MAVSDK, not run in PX4 VTOL SITL, not bench- or flight-tested. `FighterModelInputs` (18 m/s cruise, 30° planning bank, 250 m forward / 200 m back transition) and `SurveyLimits` are **model inputs / development placeholders**, not measurements of this airframe or its PX4 parameters. Wind, climb, terrain, obstacles and energy are not modeled.
