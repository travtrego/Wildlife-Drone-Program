# Coyote requirements and decisions

Maintained design record. Reconciled **2026-10-17** from the October 15 baseline and supplied desk review; **owner decisions of 2026-10-18** applied below (see decision history).

## Established requirements

| ID | Requirement | Acceptance evidence still needed |
|---|---|---|
| R1 | Six-rotor Coyote; distinct from Fighter VTOL and X500 | Exact layout, propulsion and control configuration |
| R2 | Full sensing suite permanently installed; no routine mission swaps/removals to meet mass limits | Dimensioned installation, weighed mass, CG and field-of-view study |
| R3 | Sony high-resolution RGB stills camera, a permanently installed stabilized zoom/thermal/rangefinder gimbal (telephoto and thermal capability live here), OAK-D-class depth, JT128-class LiDAR, RTK, Jetson-class compute and Pixhawk-class autopilot | Exact SKUs, electrical/data interfaces and science performance, including resolving identifying marks at the operating stand-off distance |
| R4 | Build a population database of individually identified coyotes from weekly survey runs over Island Park (Portsmouth, RI) and nearby marshes (not Common Fence Point); also supports mapping, perception and autonomy research. Identification is human-confirmed; documentary-grade video is not required | Defined individual-ID criteria, database schema, stand-off distance, survey route and field/permit protocol |
| R5 | At least 20 minutes usable flight with all hardware installed, landing with at least 25% battery remaining; 25–30 minutes is a stretch goal | Representative logged hover/mission qualification |
| R6 | PX4 retains stabilization, geofence, battery/link failsafes, return home and pilot override; Jetson requests mission actions. Companion authority (`operator_delegated`) is granted by a ground-station command and is revoked on any PX4 failsafe, telemetry-link loss or pilot takeover; it returns only when the operator re-sends the command. The ground station notifies the operator, with the reason, whenever authority is revoked. The command may be sent on the ground before takeoff and covers one flight. With the operator on site, the Jetson may request the takeoff after the operator arms; the Jetson never arms the vehicle (2026-10-20) | Configuration and failure-mode testing, including SITL tests of each revocation path and the notification |
| R7 | Required sensor concurrency must be supported | Peak power, cooling, bandwidth, storage and synchronization budgets |
| R8 | Simulation and appropriate X500/bench validation precede promotion to Coyote | Versioned test records; see [evidence index](../docs/VALIDATION.md) |
| R9 | Takeoff mass below 55 lb (24.9 kg), so operations stay under normal Part 107 rules without an exemption | Weighed, fully equipped aircraft with the selected battery |
| R10 | Battery selected by current first: continuous discharge rating at least about 2× hover current (about 130 A on current estimates), then capacity | Pack datasheet plus measured hover/peak current and temperature |

Installed mass and drag apply even when a sensor is off. Average power/heat depend on duty cycle; electrical and cooling design must cover required simultaneous operation.

## Candidate decisions, not procurement approval

| Item | Current engineering baseline | Status |
|---|---|---|
| Frame | EFT E616P | Owner-selected candidate; revision/fit/performance unverified |
| RGB stills | Sony ILX-LR1 + FE 85mm F1.8 on Gremsy Pixy LR | Owner-selected 2026-10-18 (P1); fit, balance, interfaces and installation unverified |
| Zoom / thermal / rangefinder | SIYI ZT30-class integrated gimbal | Owner-selected 2026-10-18 (P1); also provides the permanent thermal capability. Optical/thermal performance for coyote ID unverified |
| Thermal (dedicated) | FLIR Boson+ 640-class | Dropped 2026-10-18; integrated ZT30-class thermal used instead (no radiometric data requirement) |
| Depth / LiDAR | OAK-D Pro W / Hesai JT128-class | Baseline/candidate; placement, blind zones and calibration open |
| Compute / autopilot / navigation | Orin NX 16GB / Pixhawk 6X / F9P classes | Exact assemblies and interfaces open |
| Communications | Broadband IP and independent pilot/telemetry link | Architecture selected; radios and failover open |
| Propulsion / battery | Six Hobbywing X8 G2 units; 12S packs meeting R10 | X8 G2 adopted as model input 2026-10-18 (P2), pending clamp fit on the exact E616P arm; pack unselected |

The former T7 + original SEL70200G arrangement is superseded by the P1 split setup; original SEL70200G and extending SEL70200G2 must still not be silently interchanged if it is revisited. Component masses and sources belong in [bom.csv](bom.csv).

## Procurement gates — all remain open

| Gate | Required proof |
|---|---|
| G1 — geometry | Exact E616P revision/kit inventory and drawing; usable bay, arms, battery tray, landing and gimbal clearances |
| G2 — imaging | Sony/85mm/Pixy LR balance and full-axis sweep; ZT30-class gimbal mounting, power and data; resolution of identifying marks at stand-off distance (owner skipped the pre-purchase target test on 2026-10-18; see risk below) |
| G3 — permanent layout | Full mounts, CG envelope, rotor/FOV occlusion, vibration, weather protection and maintainability |
| G4 — propulsion/power | Exact thrust/current curves and continuous/peak/thermal limits; clamp fit; protected rails; battery sag/BMS/connector and reserve |
| G5 — sensing/data | Thermal SKU/FOV/pointing; timebase, calibration, interfaces, throughput, recording and cooling |
| G6 — operations | Feasible useful duration, applicable operating pathway, site/wildlife constraints, pilot control and progressively qualified tests |

See [feasibility](ENGINEERING_FEASIBILITY.md) for screening calculations. Current modeled configurations do not demonstrate the endurance target under the study's proposed weight boundary. This is not a proof that all possible permanent-suite designs fail.

## Conflicting specifications — unresolved

The October 15 sources quote E616P wheelbase around 1644/1648mm and inconsistent overall envelopes: approximately 2429×1733×599mm, 2429×2429×599mm and 1738×1517×652mm. These are conflicting historical listing claims, not interchangeable CAD dimensions. Kit inclusions and whether measurements include propellers remain unresolved. Obtain a dated exact-revision drawing before using any envelope for fit.

Gimbal payload rating does not establish geometric compatibility. T7 depth is referenced from camera CG; total camera+lens length alone neither proves fit nor disproves it. Motor-out safety likewise cannot be inferred from five motors' summed maximum thrust.

## Review proposals — owner dispositions 2026-10-18

The [supplied review](reviews/README.md) proposed:

| ID | Proposal | Disposition / required evaluation |
|---|---|---|
| P1 | Sony/Pixy LR/85mm stills plus permanent SIYI ZT30 zoom/thermal gimbal | **Adopted** 2026-10-18; Boson+ dropped. Resolution target test skipped by owner choice |
| P2 | X8 G2 mass/curve in place of original X8 screening input | **Adopted as model input** 2026-10-18, pending clamp fit and exact SKU/source reconciliation |
| P3 | Select battery by current first; proposed >=130A continuous | **Adopted** as R10, 2026-10-18 |
| P4 | More conservative energy/load assumptions and >=20min useful target; 25–30min stretch | **Adopted** as revised R5, 2026-10-18 |
| P5 | Machine-readable BOM and regenerating model | **Adopted** 2026-10-18; CSV ledger exists, executable model to follow in a separate change |
| P6 | Funder/procurement eligibility review if applicable | **Not applicable** 2026-10-18: personally funded. Revisit if grant or agency funding is added |

The owner confirmed on 2026-10-18 that the goal is a population database of individual coyotes from weekly runs (R4). Proposed human-confirmed identification and fox-study comparisons are research inputs, not demonstrated coyote-ID capability.

**Open risk:** the owner chose to skip the pre-purchase resolution test. Nothing yet shows the selected cameras resolve identifying marks (ear notches, scars, muzzle/chest/leg coat detail) at a stand-off distance that avoids disturbing coyotes. Review the first real survey imagery before further imaging purchases.

## Decision history

- October 14: E616P preferred candidate; full suite permanent, no mission swaps.
- October 15: original Sony 70–200/T7 preferred for evaluation; feasibility study and review brief prepared.
- October 17: documentation consolidated; supplied October 15 desk review registered. No component substitution, purchase approval, changed endurance target or hardware validation.
- October 18 (owner, Travis): R4 survey goal and area, R5 ≥20 min with 25% reserve, R6 ground-station delegation with revocation and notification, new R9 (<55 lb) and R10 (battery current rule); P1 split camera adopted and Boson+ dropped; P2 X8 G2 model input; P5 model approved; P6 not applicable; resolution test skipped. Action-gate limits stay development placeholders until PX4 geofence/battery parameters are set. Procurement gates remain open; no purchase approved. Working list: project file `coyote/open-decisions.md`.
- October 20 (owner, Travis): R6 delegation may be granted on the ground before takeoff (one flight per grant). Option 1 adopted: with the operator on site, the Jetson may request takeoff once the operator has armed; arming stays with the operator. Unattended or docked launches are not adopted.
- October 21 (owner, Travis): X500 scope is waypoint autonomy only (no Jetson, perception or AI mission logic). For R8, X500 validation covers the shared multirotor flight layer; Coyote perception/AI logic is validated in simulation and then on Coyote itself.

Accepted future changes need date, owner decision, affected requirement, exact variant/source and acceptance evidence. [Issue #3](https://github.com/travtrego/Wildlife-Drone-Program/issues/3) tracks execution; this file owns the maintained requirements and decisions.
