# COYOTE — Hexacopter Platform Master Engineering Report
**Status:** consolidated decision record / Claude handoff — v1.0  
**Prepared:** 2026-10-15  
**Repository:** [Wildlife-Drone-Program](https://github.com/travtrego/Wildlife-Drone-Program)  
**Scope:** **Coyote heavy-duty six-rotor wildlife research platform ONLY**. Fighter 2430 VTOL is a separate long-endurance aircraft. X500 V2 is the test/reference aircraft, not the final Coyote.  
**Evidence status:** synthesized from earlier user decisions, current GitHub documentation and published vendor specifications; not independently peer-reviewed by Claude, manufacturer-certified, or flight-tested. All quoted component masses and vendor figures require revision/SKU checks prior to purchasing.

## 1. Executive decision summary

**Owner-established requirements (do not silently change):**
1. Build **Coyote as a hexacopter**, not the Fighter VTOL and not the X500 quadcopter.
2. Preferred frame is the **EFT E616P**, an industrial folding six-rotor frame, *selected for engineering evaluation*, **not yet verified purchase-ready**.
3. Carry **one permanently installed, non-swappable full sensor/payload suite**. No routine mission-by-mission sensor or camera changes. Sensors may be selectively powered, and optical zoom is permitted, but hardware stays attached.
4. Missions: daylight/night wildlife observation and animal identification at sensible stand-off distances, high-resolution imagery, environmental surveying, 3D perception/mapping, obstacle awareness, computer vision, AI inference, SLAM/sensor fusion, and autonomous research.
5. **Target ~25–30 min useful flight endurance with every sensor mounted**; not validated or promised. Do not reach the goal by removing hardware. Optimize structure, propulsion, power, and mission plan—or revisit frame/endurance/regulatory concept—before compromising permanent payload.
6. Flight-critical stabilization, geofence, link-loss and battery failsafes, manual override and RTH live on autopilot; Jetson requests mission actions but is not permitted to bypass flight-safety boundaries.
7. Validate algorithms through simulation and X500 bench/flight testing before Coyote use. Maintain logs and acceptance evidence.

**Current overall verdict:** promising engineering concept, **procurement HOLD**. No verified CAD fit, camera/gimbal balance, thermal optical SKU, real installed mass, validated current margin, flight endurance or airworthiness testing. The project should not be presented as a final BOM.

### Design decision authority matrix

| Item | Current choice | Decision class | Evidence / restriction |
|---|---|---|---|
| Aircraft role | Close-range autonomous wildlife research/sensing | **Requirement** | Separate from Fighter VTOL |
| Motor count | 6, industrial hexacopter | **Owner-selected** | Exact X layout, arms/propulsion not frozen |
| Frame | EFT E616P | **Owner-selected candidate** | Purchase gated by CAD/fit/mass/energy |
| Payload behavior | All sensors permanently installed | **Fixed requirement** | No swapping for mission or mass savings |
| Main RGB camera | Sony ILX-LR1 61 MP | **Baseline choice** | Actual lens/control/gimbal integration remains open |
| Telephoto lens | Original Sony SEL70200G FE 70–200mm F4 G OSS | **Preferred proposal** | 840 g; remote zoom not solved |
| Gimbal | Gremsy T7 | **Preferred proposal** | Mass rating passes; camera envelope/balance unverified |
| Thermal | Permanent FLIR Boson+ 640-class (earlier Hadron/Boson explored) | **Candidate class** | Final core/lens/housing/stabilization unselected |
| LiDAR | Hesai JT128-class | **Leading candidate** | Local 3D perception, placement/FOV unknown |
| Short-range vision | Luxonis OAK-D Pro W-class | **Baseline choice** | Depth is close range; not long-range avoidance |
| Mission AI | NVIDIA Jetson Orin NX 16GB-class | **Baseline architecture** | Carrier, cooling, storage, power TBD |
| Autopilot | Pixhawk 6X-class | **Baseline architecture** | SKU, pinout, vibration and redundant power TBD |
| Navigation | F9P-class RTK GNSS | **Baseline architecture** | Antenna geometry/integration TBD |
| Communications | High-bandwidth IP link AND separate flight telemetry/command | **Required architecture** | Radio models, range and failover TBD |
| Motors/ESCs/props | 6× Hobbywing XRotor X8 + 30 in in **screening calculations only** | **Not selected** | Thrust/current/thermal/mounting validation needed |
| Power | 12S nominal; 22/26/33/36Ah example packs | **Screening assumption** | BMS/continuous current/peak/CG/flight reserve pending |
| Procurement | No full-platform part orders authorized | **HOLD** | Critical engineering gates not closed |

## 2. How we arrived here — decision history

- **2026-08-16 — original concept:** premium autonomy/robotics drone intended for professional RGB imaging, mapping, night/thermal perception, depth/LiDAR, advanced AI, local perception and fusion. The initial hardware direction featured **Sony ILX-LR1 + Gremsy Pixy LR**, **Hesai JT128**, **OAK-D Pro W**, FLIR Hadron/Boson family, Jetson Orin NX 16GB, Pixhawk 6X, and F9P-class RTK. These were plans, not confirmed purchases.
- **Late summer / October — frame alternatives:** early larger/open-frame thinking included **RJX1200D**. Comparison shifted toward industrial folding EFT families for enclosure/packaging: **E410P/E416P/E420P/E610P/E616P**. The **E420P is a quadcopter**, not the selected six-rotor Coyote. E610P remained a smaller competing hexacopter.
- **2026-10-14 — airframe decision:** project owner picked **EFT E616P**. It became the preferred engineering baseline, conditional on fitting the **complete** research payload and satisfying power/mass targets.
- **2026-10-14 — payload rule strengthened:** owner explicitly rejected sensor/payload swaps. Every selected sensor and computing component must have a permanent installed home. The previous phrasing “modular thermal payload” was superseded by permanent mounting (specific thermal part remains TBD).
- **2026-10-15 — optical reassessment:** the original Pixy LR with Sony 85mm F1.8 was judged restrictive for distant animals/birds. Proposed **Gremsy T7 + original Sony FE 70–200mm F4 G OSS (SEL70200G)** while keeping ILX-LR1. This is a **preferred candidate**, not a vendor-supported certified pair.
- **2026-10-15 — preliminary feasibility:** first all-installed mass and 12S battery/endurance screening built and logged in [ENGINEERING_FEASIBILITY.md](ENGINEERING_FEASIBILITY.md). It identified narrow under-55-lb margins and inability to demonstrate 25–30 min with the lighter pack. All estimates remain provisional.

## 3. Mission specification and suitability

### Primary planned use
- Observe and identify animals without inappropriate close approaches or disturbance; both mammals and more difficult small birds.
- Collect stabilized high-resolution visible images, day/night thermal detections, short-range stereo views, 3D LiDAR point clouds and RTK-referenced telemetry.
- AI-assisted detection, classification, tracking, mapping, environmental inspection, obstacle/terrain awareness, and research data collection.
- Combine synchronized sensor observations onboard; conduct controlled autonomous missions with a pilot override and flight-controller-enforced safety limits.

### Honest limitations
- **E616P is a large, loud industrial aircraft.** Its noise/downwash can disturb sensitive wildlife; evaluate observation distances, permissions and species-specific welfare constraints. A better zoom lens reduces the need to approach but does not guarantee identification.
- **OAK-D Pro W** is a short-range depth/perception sensor (best depth around **0.4–6 m**, useful range highly scene-dependent). It is not a substitute for long-range obstacle sensing or telephoto animal identification.
- **Hesai JT128** is promising for nearby 3D perception, with up to ~60 m marketed maximum under favorable conditions; range, object reflectivity, occlusion and rotor interference matter. It is not necessarily long-range vegetation-penetrating survey LiDAR.
- **Sony telephoto camera** can add significant identification pixels at a given stand-off, but optics, gimbal vibration, atmospheric conditions, subject angle and shutter speeds dominate real identification probability.
- **Thermal** selection requires a wildlife-relevant focal length/FOV and repeatable stabilization or precise rigid alignment. “FLIR Boson+” alone does not define a deployable sensing package.

## 4. Frame and mechanical configuration

**EFT E616P published reference:** approximately 6.41 kg frame mass, **1648 mm** wheelbase (some prior listings ~1644 mm), **40 mm arm diameter** on current official listing, 30-inch X8 or 31-inch A8-X motor reference, 12S 22Ah suggested battery, “16 kg effective load” class. **Effective load is not a validated spare capacity with our electronics and propulsion.** Official page gives unfolded 1738×1517×652 mm; earlier web listings present conflicting overall dimensions, potentially different revisions. Obtain latest exact kit drawing and part list before CAD or purchase: https://www.effort-tech.com/en/e616ps .

**Illustrative permanent placement plan — NOT an approved mounting drawing:**
- Underslung forward/center camera bay: T7 with ILX-LR1, 70–200mm lens, isolated mounting plate, adequate lens/hood/cable sweep, gimbal landing clearance and lens support.
- Upper protected area: Jetson/carrier/heatsink/storage plus insulated distribution and network components; Pixhawk vibration-isolated close to measured aircraft CG, physically away from noisy power wires and jetson/radio thermal sources.
- Raised upper location: JT128 360-degree scanning LiDAR, protected but with minimized arm/prop/antenna/battery occlusion.
- Forward unobstructed optical face: OAK-D Pro W, correct baseline/orientation and mounting protection.
- Fixed thermal camera location: to be selected with appropriate standoff lens and stabilized-or-registered pointing strategy, avoiding gimbal/LiDAR FOV conflicts.
- GNSS: RTK antenna(s) with known separation from high-current wiring and RF sources and consistent yaw/position-frame calibration.
- Batteries: mounted with documented adjustment to CG; access, enclosure and thermal/discharge considerations.

**Unproven geometry:** inner electronics compartment dimensions; avionics mounting holes; battery-tray dimensions and CG travel; landing gear to center-plate vertical clearance; gimbal rotation envelope; thermal/visible co-boresight; LiDAR blind zones; camera propeller/leg visibility; cooling ducts and IP/weather protection. A large wheelbase by itself is not evidence of available usable bay volume.

## 5. Imaging, gimbal, lens and optical control

| Optical component | Published reference | Reason |
|---|---|---|
| Sony ILX-LR1 | 61MP full frame, 100×74×42.5 mm, 243 g, 10–18V | Main high-resolution imaging and mapping body |
| Sony FE 70–200 F4 G OSS **SEL70200G ORIGINAL** | Ø80×175 mm, **840g without tripod mount**, nominal constant-physical-length internal zoom | Better long-distance optical reach; keep mass/CG geometry stable through zoom |
| Gremsy T7 | gimbal 1.86 kg, camera payload rating ~3.18 kg; published width ≤180mm, height ≤130mm (170mm with bar), depth ≤150mm *from camera CG* | Increased cage and payload over Pixy LR; actual fit unproven |
| Camera + lens **only** | 1.083 kg | Below T7 published rated payload (a necessary but not sufficient condition) |
| Camera + lens + gimbal | **2.943 kg** | Excludes all mounts, lens collar, cabling, actuators, dampers and mounting plate |
| Former alternative Pixy LR + 85mm F1.8 with ILX-LR1 | ~1.109 kg system | Lighter, but 85mm Gremsy guidance is photography only and poorer long-distance reach |

**Critical distinction:** Gremsy's depth limit is referenced to camera **center of gravity**. Simply adding Sony lens length + camera body thickness (~217.5mm) does **not** establish incompatibility. We must locate the balance point and test balance and full pitch/roll/pan travel with real mount/collar/cables. Gremsy has **not** confirmed this exact camera/lens/gimbal stack, and no physical trial has been conducted.

**Zoom complication:** SEL70200G zooms via a **mechanical ring**. The gimbal does not automatically control lens zoom. For in-flight 70–200mm adjustment, select/test an actuator and safely route its power/control. Until proven, a fixed zoom-ring setting is the honest initial integration path—not sensor swapping. Validate focus/exposure/trigger/media transfer/stream control with Sony independently of gimbal stabilization.

**Geometric, not verified identification performance:** for a ~0.3m-wide subject at 200m under ideal pinhole assumptions on ~9504-pixel Sony full-frame width, 85mm ≈34px across the subject and 200mm ≈80px. Optical/operating conditions can make actual identifiability much worse.

Vendor references: https://docs.gremsy.com/gimbals/gremsy-t7/general ; https://gremsy.com/products/gremsy-t7 ; https://www.sony.co.uk/electronics/camera-lenses/sel70200g/specifications ; https://helpguide.sony.net/ilc/2390/v1/en/contents/221h_specifications.html .

## 6. Full permanently-installed sensor and compute bill of intent

| Subsystem | Candidate | Placement/purpose | Design maturity |
|---|---|---|---|
| Daylight RGB | ILX-LR1 + original Sony SEL70200G + Gremsy T7 | Isolated ventral payload | Preferred, fit unconfirmed |
| Thermal | Boson+ 640-class; earlier Hadron/Boson considered | Fixed concurrent thermal channel | Exact SKU, FOV, stabilization, housing OPEN |
| 3D LiDAR | Hesai JT128 | Elevated view, fusion/obstacles | Leading candidate; blind-zone layout OPEN |
| Stereo/AI camera | OAK-D Pro W | Forward near-field perception | Baseline; FOV layout OPEN |
| Compute | Jetson Orin NX 16GB | ROS2/inference/fusion | Baseline; carrier/thermal/power OPEN |
| Flight controller | Pixhawk 6X | Flight critical control | Baseline; precise SKU OPEN |
| RTK navigation | F9P-class | Precise positioning and geotagging | Baseline; antenna(s)/corrections OPEN |
| RF/data | Broadband IP video/telemetry + independent control link | Separation of mission bandwidth and safe pilot control | Architecture set; radios OPEN |
| Recorder/storage | SSD, camera media, flight and sensor logging | Dataset integrity, timestamps | Details OPEN |
| Power | regulated 12S-derived rails, protected distribution and failsafes | Feed gimbal, Sony, Jetson, LiDAR etc. | Architecture must be designed, not simply connected directly |

The full **mass, drag, thermal duty and peak current** apply to every mission whether software activates all sensors or not. If component substitution becomes necessary, verify same mission capability while retaining the static fully-installed design.

## 7. Preliminary mass estimate (screening BOM v0.1)

**Manufacturer reference masses** (component data from cited source report):

| Known component | Installed kg |
|---|---:|
| EFT E616P frame | 6.410 |
| 6× Hobbywing XRotor X8 integrated motor+ESC+30in propulsion at 1.150kg each (**model only**) | 6.900 |
| Sony ILX-LR1 | 0.243 |
| Original Sony SEL70200G | 0.840 |
| Gremsy T7 | 1.860 |
| Hesai JT128 | 0.265 |
| OAK-D Pro W | 0.091 |
| **Catalogue subtotal** | **16.609** |

**Explicit placeholders, not weighed/vendor-approved SKUs:** thermal assembled package 0.150kg; Jetson carrier/case/cooling/storage 0.450; Pixhawk/RTK/control 0.450; IP/telemetry radios 0.500; power distribution/wiring/converters 0.650; structures/dampers/landing support/enclosure 1.200; collar/zoom/control/camera cabling 0.350. **Subtotal placeholders 3.750 kg.**

**Battery reference:** lightweight 22Ah 12S pack 3.421kg, *unapproved for discharge headroom*.

**Total example installed mass: 16.609 + 3.750 + 3.421 = 23.780 kg (~52.43 lb).** US 55lb is ~24.948kg, leaving **only 1.168kg** apparent headroom. Incomplete kit-inclusion lists, supports, large camera mounts, battery box, safety redundancy, thermal optics or stronger landing gear can consume that quickly. Actual frame may include/remit subsystems already counted; clarify exact EFT kit and motor clamp interfaces before trusting ledger.

**Do not quote 23.78 kg as Coyote's actual takeoff weight**; it is an assumption-rich example.

## 8. Battery, discharge and endurance feasibility (screening only)

Calculation basis: one 12S pack nominally 44.4V; Hobbywing X8 30x11 **46V** static bench interpolation near required thrust / 6; six motors; allowance 120W continuous non-propulsion load; 80% of nominal battery Wh treated as *idealized usable energy*, no measured wind/drag/temperature, no emergency reserve proof, no voltage-sag model.

```text
hover_thrust_per_motor_kg = AUW_kg / 6
hover_propulsion_W = 6 * interpolated_X8_bench_input_power(hover_thrust_per_motor_kg)
total_average_W = hover_propulsion_W + assumed_120W_nonpropulsion
idealized_minutes = pack_Wh * assumed_0.80 / total_average_W * 60
```

Hobbywing manufacturer X8 MFP 30×11 46V table publishes 3535g thrust at 317.5W and 4467g at 435.7W. **These are stationary bench operating points, not in-flight efficiency or single-motor-out assurances.** https://www.hobbywing.com/en/products/xrotor-x8108

| Example battery | Battery mass | Modeled AUW | Idealized endurance | Relative to US 55lb |
|---|---:|---:|---:|---|
| 12S 22Ah high-energy | 3.421 kg | 23.780 kg | 19.9 min | 1.17 kg below |
| 12S 26Ah Neo | 4.180 kg | 24.539 kg | 22.6 min | 0.41 kg below |
| 12S 33Ah Neo | 5.148 kg | 25.507 kg | 27.4 min | 0.56 kg ABOVE |
| 12S 36Ah Neo | 5.501 kg | 25.860 kg | 29.3 min | 0.91 kg ABOVE |
| 12S 22Ah conventional smart | 6.000 kg | 26.359 kg | 17.5 min | 1.41 kg ABOVE |

**IMPORTANT: modeled time ≠ useful mission time.** Wind, maneuvering, usable discharge energy, battery aging, vibration, changing voltage, flight-controller safety reserves and thermal derating are omitted.

**Current:** the modeled ~2.35kW load at nominal 44.4V is ~53A even at hover. The cited lightweight 22Ah pack is reported at only 66A continuous; that leaves limited margin for climb, gust response, voltage sag, and safety. A pack that reaches an idealized flight time but cannot deliver safe transient current **fails**. Also, greater battery mass increases required hover power.

**55lb regulatory concern:** typical US Part 107 small-UAS operation requires aircraft weigh **less than 55lb at takeoff including attached equipment**. The model's 33/36Ah cases exceed this; exceptions or alternative approvals are separate legal/operational planning, not automatic. Avoid designing right against this threshold with unresolved mass placeholders. See FAA: https://www.faa.gov/newsroom/small-unmanned-aircraft-systems-uas-regulations-part-107 .

**Conclusion:** the 25–30 minute target with the complete permanent payload and under 55lb is **not shown achievable** in this model. Motor/prop/battery optimization and calibrated flight power trials are required. The current E616P cannot be called “perfect” solely based on size/payload marketing.

## 9. Software, safety and data architecture

```text
Operator / science mission definition
        |
        v
Jetson Orin NX (ROS 2, Python, AI/ML, sensor fusion, timestamping)
  |- Sony camera/video/images
  |- thermal video
  |- Hesai LiDAR point clouds
  |- OAK-D image/depth inference
  |- RTK/geotag synchronization
        |
  approved mission commands (MAVSDK / MAVLink)
        v
PX4/Pixhawk 6X  -- independent manual control and telemetry
        |
  stabilization, geofence, RTL/RTH, battery and link failsafes
        v
  six motors / ESCs
```

Recommended program stack per repository: **PX4, QGroundControl, MAVSDK/Python, ROS 2, OpenCV and inference tools**. Distinguish position reporting, high-rate sensor storage and low-rate safety commands. Plan a shared timebase (GNSS/PPS/PTP or validated alternative), sensor frames/extrinsics, calibration, and rigorous logs for reproducible wildlife data.

**Testing ladder:** code/unit tests → PX4 SITL → hardware-in-loop/bench → X500 reference flights → reviewed logs/flight envelope → Coyote ground test/hover validation → progressively complex autonomous field trials. X500 is being mechanically assembled separately and is not a proxy for proving E616P structural/thermal endurance.

Safety-related requirements: operator command authority, geofences, RTL, degraded GPS actions, motor/ESC failure behavior, independent RF control, battery margin, recording of control-state transitions, no dangerous autonomous maneuvers based solely on experimental ML output.

## 10. Fit and integration study required before spending money

| Gate | Actual evidence needed | Why |
|---|---|---|
| E616P mechanical revision | Dated vendor drawing/STEP, precise kit inventory, inner bay, landing gear, battery tray, 40mm arm clamps, folding clearance | Overall wheelbase does not prove components fit |
| T7/Sony balance | Gremsy written approval OR photographed measurement/mockup of original SEL70200G+ILX-LR1 with support/cables/zoom | Mass capacity ≠ envelope capacity |
| Optical fields of view | CAD ray trace or measured visibility for LiDAR 360°, OAK, thermal, Sony pan/tilt with rotors/legs/battery | Avoid blind sectors and self-occlusion |
| Thermal channel | Exact Boson+/Hadron variant, focal length, housing, optical pointing and stabilization, environmental constraints | Bare thermal core is not an operable permanent sensor |
| Camera integration | Camera power/trigger/video/AF/zoom control proven | A stabilized gimbal does not imply full camera control |
| Propulsion | 6-motor thrust curves, efficiency and thermal margin at target AUW; 30-inch prop spacing; ESC protocols and emergency behavior | Does not inherit from advertised 16kg load |
| Power design | Correct regulator rails, high-current cables, fuse/isolation, peaks, battery current rating and voltage sag, charger/storage plan | Batteries must safely deliver mission power |
| CG/structure | Actual full loaded mass, moments and CG battery travel; vibration, wind load, gimbal attachment strength | Permanent array can be front/top-heavy |
| Environmental/EMI | Rain/dust claims, ventilation, thermal sensors, RF/compass and LiDAR EMC assessment | Industrial agricultural frame is not automatically electronics-weatherproof |
| Regulatory and wildlife | Appropriate FAA operational pathway, pilot qualification, site/specific-species rules/permits and no-disturbance ranges | Legal/ethical deployment |

**Engineering release rule:** no SKU purchasing or procurement authorization implied by this document. Close all critical interface/safety gates first and capture evidence with date, source, specific component variant and reviewer.

## 11. Open choices — in priority order

1. **EFT E616P verified exact revision and mechanical CAD:** dimensions of empty central bay, lower payload interface, landing leg vertical clearance and battery holder. Confirm all parts included.
2. **Gremsy T7 and Sony SEL70200G mechanical/electrical pairing:** physically balance/test with collar and cabling; inspect pan/tilt clearance; decide long-lens zoom drive and AF/trigger support.
3. **Specific permanent thermal package:** Boson+ 640 lens/FOV and stabilization plan; thermal and RGB co-registration and mass.
4. **Structural mounting plan:** permanent custom brackets/dampers/mast; vibration, LiDAR/thermal/RGB occlusion, antenna placement, access/maintainability.
5. **Real propulsion and power architecture:** compare X8 with viable alternatives at total full installed mass, propulsion margin, battery continuous/peak current, safe flight reserve and verified 25–30 min mission time.
6. **Complete exact BOM and BOM status:** chosen vs candidate vs purchased vs tested, mass, power idle/peak, dimensions, connector, interface, supplier/doc and cost.
7. **Firmware/compute interface details:** RTK corrections, MAVLink, ROS2 topic/data-rate plan, Wi-Fi/IP vs backup control, time sync, onboard SSD.
8. **Flight qualification and regulatory plan:** hardware bench, instrumented hover, logs, animal welfare and environment-specific procedures.

### Vendor question packs

**EFT:** Request latest **E616P** STEP/dimension drawings; frame-only kit BOM with installed-vs-optional masses, 40mm arm clamp/30-inch prop compatibility; exact internal bay and landing gear/payload mount measurements, battery dimensions/CG envelope; environmental protection details.

**Gremsy:** Ask about **T7** compatibility with **ILX-LR1 and *original* SEL70200G**, with available mounting sliders, lens collar/support, CG range, full axes travel, harness routing, camera power/trigger/zoom options; request confirmation in writing or a supported test configuration.

**Sony / payload integrator:** Verify E-mount compatibility, AF/focus behavior on ILX-LR1, control protocols/power/video, and reliable in-flight zoom mechanism/independent lens support.

**Hobbywing/battery suppliers:** Confirm X8 40mm clamp and 30-inch prop installations, continuous thrust/ESC thermal operation, peak/continuous current and C-rate of exact battery SKU, connector/fusing, BMS low-voltage constraints and available high-density packs.

## 12. Program integration and boundaries

- **Coyote is not the Fighter 2430 VTOL.** The Fighter is a different 4+1 lift-and-cruise aircraft for endurance and wide-area surveys; avoid carrying over its autopilot or payload/battery assumptions uncritically.
- **X500 V2** is the user’s current assembly and low-risk PX4/MAVSDK reference bench. It is not sized for Coyote's complete heavy sensor suite.
- **Shared software** is inherited only after validation. Keep Coyote hardware-specific configs inside `coyote/`, promote code with stable tested interfaces into `shared/`.
- The role of the six-rotor Coyote is persistent multichannel close-range observation / sensing; it must not be forced to meet long-range VTOL mission profiles.

## 13. Report limitations and source ledger

This report consolidates known design conversations and documents in this repository. It is not a record of a hardware purchase, vendor communication, CAD fit, flight test or formal third-party review. Information missing from accessible historical context should be marked **UNKNOWN**, not filled in by assumption.

Primary sources:
- Coyote current specifications: [README.md](README.md)
- Preliminary full weight/power/camera study: [ENGINEERING_FEASIBILITY.md](ENGINEERING_FEASIBILITY.md)
- Program architecture: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- GitHub open frame/propulsion issue: https://github.com/travtrego/Wildlife-Drone-Program/issues/3
- EFT E616P current product listing: https://www.effort-tech.com/en/e616ps
- Gremsy T7 FAQ/geometry: https://docs.gremsy.com/gimbals/gremsy-t7/general
- Sony original SEL70200G: https://www.sony.co.uk/electronics/camera-lenses/sel70200g/specifications
- Hobbywing X8 curve: https://www.hobbywing.com/en/products/xrotor-x8108
- FLIR Boson+: https://oem.flir.com/products/boson-plus/
- Hesai JT128: https://www.hesaitech.com/product/jt128/
- Luxonis OAK-D Pro W: https://checkout.luxonis.com/products/oak-d-pro-w
- FAA Part 107 summary: https://www.faa.gov/newsroom/small-unmanned-aircraft-systems-uas-regulations-part-107

## 14. Specific questions for Claude's independent engineering review

Treat this report and [ENGINEERING_FEASIBILITY.md](ENGINEERING_FEASIBILITY.md) as *input claims to challenge*, not as proven facts. Do NOT approve parts because they were previously recommended. Produce a **findings-first** audit with:
1. Calculational errors or overlooked mass/power items, including frame-kit double-counting, 12S voltage, thermal and discharge current margins, redundancy, reserve.
2. E616P dimensional and 30-inch six-rotor clearance concerns and likely unavailable center-bay/landing-gear geometry, emphasizing missing manufacturer CAD.
3. T7 + original Sony 70–200 + ILX-LR1 fit/control/zoom/lens-support risk; viable modifications that **retain permanent sensor hardware**.
4. Whether FLIR Boson+ / JT128 / OAK-D together add meaningful capabilities for actual wildlife detection and autonomy, with overlapping FOV/functional limitations.
5. Regulatory/airworthiness/wildlife impact risks that may block the operating concept.
6. Ranked corrective actions, owner/vendor evidence required, and specific changes recommended. Label each as **confirmed, calculated, provisional, or unknown**.

**Claude-review status:** NOT YET RUN. This file is prepared so an external Claude/Claude Code reviewer can work from the identical source of truth.
