# Coyote requirements and decisions

Maintained design record, reconciled **2026-10-17** from the October 15 baseline and supplied desk review. This cleanup adopts no new hardware or endurance requirement.

## Established requirements

| ID | Requirement | Acceptance evidence still needed |
|---|---|---|
| R1 | Six-rotor Coyote; distinct from Fighter VTOL and X500 | Exact layout, propulsion and control configuration |
| R2 | Full sensing suite permanently installed; no routine mission swaps/removals to meet mass limits | Dimensioned installation, weighed mass, CG and field-of-view study |
| R3 | Sony high-resolution RGB with stabilized telephoto capability, permanent thermal, OAK-D-class depth, JT128-class LiDAR, RTK, Jetson-class compute and Pixhawk-class autopilot | Exact SKUs, electrical/data interfaces and science performance |
| R4 | Wildlife observation/identification, mapping, perception and autonomy research | Defined species/individual-ID criteria, standoff and field protocol |
| R5 | Approximately 25–30 minutes useful endurance with all hardware installed is the current target | Useful-time/reserve definition and representative logged qualification |
| R6 | PX4 retains stabilization, geofence, battery/link failsafes, return home and pilot override; Jetson requests mission actions | Configuration and failure-mode testing |
| R7 | Required sensor concurrency must be supported | Peak power, cooling, bandwidth, storage and synchronization budgets |
| R8 | Simulation and appropriate X500/bench validation precede promotion to Coyote | Versioned test records; see [evidence index](../docs/VALIDATION.md) |

Installed mass and drag apply even when a sensor is off. Average power/heat depend on duty cycle; electrical and cooling design must cover required simultaneous operation.

## Candidate decisions, not procurement approval

| Item | Current engineering baseline | Status |
|---|---|---|
| Frame | EFT E616P | Owner-selected candidate; revision/fit/performance unverified |
| RGB body | Sony ILX-LR1 | Baseline; interfaces and installation unverified |
| Lens/gimbal | Original SEL70200G 70–200 F4 + Gremsy T7 | Preferred proposal; fit/balance, support, travel and mechanical zoom drive unproven |
| Thermal | FLIR Boson+ 640-class | Candidate class; lens, radiometry needs, housing and pointing open |
| Depth / LiDAR | OAK-D Pro W / Hesai JT128-class | Baseline/candidate; placement, blind zones and calibration open |
| Compute / autopilot / navigation | Orin NX 16GB / Pixhawk 6X / F9P classes | Exact assemblies and interfaces open |
| Communications | Broadband IP and independent pilot/telemetry link | Architecture selected; radios and failover open |
| Propulsion / battery | Six X8 units and 12S packs in screening study | Model inputs only; exact motor generation, prop and pack unselected |

The older Pixy LR/85mm arrangement is a fallback, not an accepted replacement. Original SEL70200G and extending SEL70200G2 must not be silently interchanged. Component masses and sources belong in [bom.csv](bom.csv).

## Procurement gates — all remain open

| Gate | Required proof |
|---|---|
| G1 — geometry | Exact E616P revision/kit inventory and drawing; usable bay, arms, battery tray, landing and gimbal clearances |
| G2 — imaging | Exact Sony/lens/gimbal balance and full-axis sweep; lens support, power, AF, trigger/data and zoom control |
| G3 — permanent layout | Full mounts, CG envelope, rotor/FOV occlusion, vibration, weather protection and maintainability |
| G4 — propulsion/power | Exact thrust/current curves and continuous/peak/thermal limits; clamp fit; protected rails; battery sag/BMS/connector and reserve |
| G5 — sensing/data | Thermal SKU/FOV/pointing; timebase, calibration, interfaces, throughput, recording and cooling |
| G6 — operations | Feasible useful duration, applicable operating pathway, site/wildlife constraints, pilot control and progressively qualified tests |

See [feasibility](ENGINEERING_FEASIBILITY.md) for screening calculations. Current modeled configurations do not demonstrate the endurance target under the study's proposed weight boundary. This is not a proof that all possible permanent-suite designs fail.

## Conflicting specifications — unresolved

The October 15 sources quote E616P wheelbase around 1644/1648mm and inconsistent overall envelopes: approximately 2429×1733×599mm, 2429×2429×599mm and 1738×1517×652mm. These are conflicting historical listing claims, not interchangeable CAD dimensions. Kit inclusions and whether measurements include propellers remain unresolved. Obtain a dated exact-revision drawing before using any envelope for fit.

Gimbal payload rating does not establish geometric compatibility. T7 depth is referenced from camera CG; total camera+lens length alone neither proves fit nor disproves it. Motor-out safety likewise cannot be inferred from five motors' summed maximum thrust.

## Pending proposals — owner decisions not made

The [supplied review](reviews/README.md) proposes:

| ID | Proposal | Disposition / required evaluation |
|---|---|---|
| P1 | Sony/Pixy LR/85mm stills plus permanent SIYI ZT30 zoom/thermal gimbal | Pending; changes where telephoto capability lives and may change thermal science capability; account for both mounts and retained/replaced thermal |
| P2 | X8 G2 mass/curve in place of original X8 screening input | Pending exact SKU/source reconciliation; no automatic 0.33kg saving |
| P3 | Select battery by current first; proposed >=130A continuous | Pending load/transient/thermal analysis; proposed margin is not an established requirement |
| P4 | More conservative energy/load assumptions and >=20min useful target; 25–30min stretch | Pending; R5 remains unchanged; define reserve separately from available-energy derating |
| P5 | Machine-readable BOM and regenerating model | CSV ledger introduced by this cleanup; executable model remains future work |
| P6 | Funder/procurement eligibility review if applicable | Pending operating/funding context and current rule verification |

The review reports individual coyote identification as the owner goal and documentary-grade video as unnecessary. Confirm those details directly before changing R3/R4. Proposed human-confirmed identification, distance trials and fox-study comparisons are research inputs, not demonstrated coyote-ID capability.

## Decision history

- October 14: E616P preferred candidate; full suite permanent, no mission swaps.
- October 15: original Sony 70–200/T7 preferred for evaluation; feasibility study and review brief prepared.
- October 17: documentation consolidated; supplied October 15 desk review registered. No component substitution, purchase approval, changed endurance target or hardware validation.

Accepted future changes need date, owner decision, affected requirement, exact variant/source and acceptance evidence. [Issue #3](https://github.com/travtrego/Wildlife-Drone-Program/issues/3) tracks execution; this file owns the maintained requirements and decisions.
