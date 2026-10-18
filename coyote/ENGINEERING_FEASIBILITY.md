# Coyote E616P + fixed multi-sensor payload: engineering feasibility v0.1

**Reviewed:** 2026-10-15
**Decision:** HOLD — preliminary engineering model, not a vendor-certified fit, airworthy configuration, verified flight endurance or purchasing authorization.
**Requirements and gates:** maintained in [DECISIONS.md](DECISIONS.md). This study evaluates the October 15 permanent-suite screening configuration (T7 + 70–200, Boson+, original X8). The owner adopted the review's P1–P5 changes on 2026-10-18; the tables below are **not yet recalculated** for them.
**Frame candidate:** EFT E616P folding six-rotor frame. Candidate, not purchased or mechanically validated.

## Executive finding

- No manufacturer-certified compatibility found for **Gremsy T7 + Sony ILX-LR1 + original Sony FE 70–200mm F4 G OSS (SEL70200G)**. The **camera + lens weigh ~1.083 kg**, safely below the **3.175–3.18 kg T7 camera payload rating**, but *payload rating does not prove camera cage fit or balance*. Camera + lens + T7 total ~2.943 kg excluding supporting hardware.
- Gremsy specifies **150 mm maximum camera depth measured from camera center of gravity**, **130 mm camera height (up to 170 mm using extension bar)** and **180 mm maximum width**. Sony lens is **175 mm long** and camera body is **42.5 mm deep**, with an approximate overall front-to-back stack of **217.5 mm**, subject to mount seating. This does **not automatically violate the 150 mm from-CG rule**, but the full assembly CG, lens collar, front balance adjustment, gimbal travel and cabling must be measured.
- T7 is **not waterproof** and Sony ILX-LR1 is specified for **0–40°C** operation. Aircraft enclosure/weather protection and active thermal design are required.
- With one manufacturer-documented propulsion *modeling candidate* (six Hobbywing XRotor X8 integrated 30-inch power units), the single-battery weight budget is only **~1.17 kg below the US 55 lb small-UAS threshold** in the 22 Ah lightweight-battery example. A larger pack may exceed it. Estimate is highly sensitive to unconfirmed mounts, wiring, gimbal clearance, real battery and frame configuration.
- A simplified bench-thrust-based nominal energy model yields **~20 minutes** for a light 22Ah/12S battery, **~23 minutes** for 26Ah and **~27 minutes** for 33Ah, the latter exceeding 55 lb on current assumptions. THESE ARE IDEALIZED SCENARIOS, NOT FLIGHT ENDURANCE PREDICTIONS. Our 25–30 minute goal **is not demonstrated**.
- Static sensing architecture is feasible in principle but exact E616P electronics, landing-gear and mast geometries remain unknown. No dimensioned installation drawing or FOV clearance study has been completed.

## 1. Camera/gimbal dimensional fit gate

| Element | Published constraint/data | Implication |
|---|---|---|
| Sony ILX-LR1 | 100 × 74 × 42.5 mm; 243 g; 1/4-20 tripod mounting plus M3 mounting holes | Camera body mount exists; need proper bracket, screw engagement and strain relief |
| Sony SEL70200G **original** | Ø80 × 175 mm; 840 g *without* tripod mount; internal zoom design | Lens+body extends ~217.5 mm before collar, hood/cables; mass is front-biased; balance unknown |
| Gremsy T7 | 1,860 g; 3,175 g camera payload; width <=180 mm; height <=130 mm (up to 170 with extension); depth <=150 mm **from CG** | Load rating passes for 1,083 g camera/lens; fit and tilt/pan/roll sweep NOT confirmed |
| T7 power/environment | 15–52V supply; not waterproof | Require regulated feed / environmental protection consistent with installed electronics |
| Camera power/environment | 10–18 V input; ~3.8 W still / 6.5 W video; rated 0–40°C | Separate power integration needed; prevent 12S direct connection to camera |
| Lens zoom/control | Mechanical zoom ring, no documented T7 zoom drive for this pairing | In-flight 70–200 mm optical zoom needs proven actuator; static camera mount does NOT mean variable focal length is automatically controllable |

**Questions for Gremsy or a physical fit mockup:**
1. Can the ILX-LR1 + original SEL70200G + any necessary support collar mechanically balance through all three T7 axes? Supply usable CG/balance adjustment, camera plate offsets, extension bar and mount drawings.
2. Is unrestricted pitch down/forward/pan possible with HDMI/USB/power leads and zoom-drive hardware without contact?
3. How does the T7 interface with this Sony model for trigger, video/data and focus? Which adapter harness/SDK is required?
4. Is an approved 70–200 lens support bracket necessary to avoid cantilevering lens loads through camera mount?
5. What load at the E616P's landing gear / payload interface and ground clearance is required to protect the T7 on landing?

**Status: OPEN. No claim of certified fit, no manufacturer contacted on the user's behalf.**

## 2. Installed mass ledger (one 12S battery)

The maintained [component ledger](bom.csv) contains quantities, per-item mass, evidence class, design status, source and unknown ownership/installation/test status. See [BOM.md](BOM.md) for schema and update rules. Inputs below were reconciled with that ledger during the October 17 documentation cleanup; the model remains the October 15 scenario.

Catalogue-claim subtotal **16.609 kg** + assembly placeholders **3.750 kg** + example 22Ah battery **3.421 kg** = **23.780 kg**. These are modeled values, not weighed aircraft data. Recalculate scenarios whenever the ledger changes.

Potential duplication or omissions remain: exact frame-kit inclusions are unknown and subsystem placeholders may hide additional mounting, electrical or structural hardware. Do not treat this as a final BOM or procurement authorization.

## 3. Battery and endurance scenarios (NOT flight-qualified)

For *reproducible screening only*, approximate hover propulsion draw using manufacturer bench data for **Hobbywing XRotor X8 / MFP 30×11 at 46 V**. At 3.535 kg of thrust X8 uses 317.5 W per motor; at 4.467 kg, 435.7 W; **linearly interpolate** between published operating points. Assume six equal rotors, no wind, 120 W combined non-propulsion average electronics (scenario allowance, not measured), 80% nominal battery energy usable, and constant battery nominal voltage for current estimation.

`Required thrust per motor (g) = takeoff_kg × 1000 / 6`

`Propulsion W = 6 × interpolated X8 W at that thrust`

`Mission minutes = (battery_wh × 0.80) / (propulsion_W + 120) × 60`

| Single battery / nominal energy | Battery weight | Estimated full AUW | Motor hover + avionics draw | Idealized battery-limited time | Relative to 55 lb |
|---|---:|---:|---:|---:|---|
| Tattu 12S **22Ah semi-solid** 976.8 Wh | 3.421 kg | **23.780 kg** | ~2.351 kW | **19.9 min** | ~1.17 kg below |
| Tattu Neo **26Ah 12S** 1154.4 Wh | 4.180 kg | **24.539 kg** | ~2.447 kW | **22.6 min** | ~0.41 kg below |
| Tattu Neo **33Ah 12S** 1465.2 Wh | 5.148 kg | **25.507 kg** | ~2.570 kW | **27.4 min** | ~0.56 kg ABOVE |
| Tattu Neo **36Ah 12S** 1598.4 Wh | 5.501 kg | **25.860 kg** | ~2.615 kW | **29.3 min** | ~0.91 kg ABOVE |
| Conventional Tattu **22Ah smart** 976.8 Wh | 6.000 kg | **26.359 kg** | ~2.678 kW | **17.5 min** | ~1.41 kg ABOVE |

**Major caveats:**
- Manufacturer X8 test thrust table is static bench data at sea level/room temperature; it is NOT validated installed-aircraft efficiency or controlled-flight endurance. Losses from rotor interference, payload drag, wind, maneuvers, changing pack voltage, converters, temperature, current capability, degraded battery, and flight contingencies can reduce mission time.
- 80% nominal energy usable is a **screening assumption**, not an adequate validated emergency reserve policy.
- Tattu 22Ah high-density pack publishes only **66 A max continuous**. The 23.78kg case would require approximately **53 A at nominal 44.4V just to hover**; limited overhead remains for climb, gusts, control authority, or failures. **Do not approve this battery based on nominal energy alone.** Screen peak discharge, voltage sag, BMS behavior and redundant power separately.
- Tattu Neo 26/33/36Ah examples are candidate manufacturer specifications, not approved batteries; verify discharge and battery tray clearance, BMS/ESC support, packing and connector.
- Raising battery capacity can *increase* hover power due to added mass, as illustrated by the table.
- All models must satisfy appropriate US operating requirements. Normal Part 107 small-UAS operations require <55 lb total at takeoff; heavier aircraft need a different regulatory approval path.

### Non-propulsion 120 W preliminary allowance

Example peak/nominal design accounting: Jetson 25–40 W (config dependent); JT128 ~15 W typical in some conditions, up to 30 W peak; OAK-D Pro W up to 7.5 W (product page); Sony 3.8–6.5 W (mode dependent); T7 ~9 W dynamic from published current at 14.5 V; thermal assembly ~2–10 W placeholder; radios, flight controls, GNSS, power conversion/zoom/fan ~20–40 W placeholder. The sum varies by operating configuration. Electrical design must support transient peaks even when average budget uses 120 W.

## 4. Physical layout: assumption vs required evidence

- **Front/lower center:** T7 + ILX-LR1 + 70–200; full cage is ~345 × 260 × 253 mm overall according to a current reseller spec. E616P total frame height is ~599–652 mm depending on manufacturer's page/version. Total height ≠ clearance under the center plate. **Actual vertical ground clearance unverified.**
- **Forward:** OAK-D Pro W with unobstructed short-range wide FOV. Sensor is 97 × 29.5 × 23.1 mm and 91 g, but mount location and rotor/arm occlusion unresolved.
- **Upper mast/plate:** Hesai JT128 (Ø62.5 × 73 mm, 265 g, 360° ×189° coverage). FOV is likely partially obscured by battery enclosure, GNSS, wiring and rotors without an elevation and occlusion model.
- **Thermal:** Permanent FLIR Boson+ 640 lens/optics, housing and mounting angle still unselected. A bare thermal camera is not a finished, environmentally protected or stabilized optical payload. Specify wildlife-relevant FOV and stabilizing/pointing needs.
- **Electronics:** Jetson + Pixhawk must be separated for EMI, vibration and heat. E616P enclosure *usable internal volume, mounting hole patterns, airflow and ingress protection remain unverified*.
- **Batteries:** EFT frame drawing is required to verify the **exact** high-density pack dimensions and CG travel.
- **Rotor placement:** 30-inch radius ~381 mm. Measure arm geometry and separation to avoid hard interference with sensor heads and required mounting mast heights; CAD is pending.

**Status:** plausible packaging envelope; no verified fit check. A dimensioned model or vendor-supplied STEP/STP assembly and 1:1 fit mockup remain required.

## 5. Historical study checklist / current procurement gates

The following is the October 15 study checklist, retained for calculation context. [DECISIONS.md](DECISIONS.md#procurement-gates--all-remain-open) owns current gate status; the [review register](reviews/README.md) records later input. A checked modeling task is not a closed procurement gate.


- [x] Owner elected **permanent, non-swappable payload**.
- [x] EFT E616P selected as preferred hex frame.
- [x] Candidate long lens = Sony original SEL70200G; candidate large gimbal = Gremsy T7.
- [x] Preliminary sensor mass ledger, propulsion comparison and nominal energy tradeoffs calculated from published specifications.
- [ ] Obtain E616P exact kit-inclusion list, dimensioned STEP/STP drawings, battery-bay dimensions, landing-gear clearance and mounting details. Confirm published E616P ~1644 vs 1648mm wheelbase and ~599 vs 652mm frame height variants.
- [ ] Obtain Gremsy T7 + Sony ILX-LR1 + original SEL70200G physical clearance/balance approval, or build representative mockup; specify lens support and zoom mechanism.
- [ ] Choose FLIR Boson+ lens/variant and permanent optical mount with stabilized vs rigid pointing requirement.
- [ ] Select actual Jetson carrier, data radios, RTK/GNSS and mounts; replace all mass placeholders with manufacturer part/SKU and measured weight.
- [ ] Produce STEP based full-aircraft CAD, unobstructed camera pan/tilt sweep, JT128/OAK/thermal field-of-view occlusion model and center-of-gravity envelope with installed battery.
- [ ] Select actual propulsion and verify tested current/thrust, motor-clamp diameter, continuous thrust and thermal margin, all six ESCs and prop clearance under single-motor-out handling requirements.
- [ ] Select the battery based on continuous and transient current, protection, sag, weight and enclosure fit; compute/validate power harness/regulator sizing and transient supply.
- [ ] Establish flight target and regulatory operating concept. Current 25–30 minute endurance **is not validated for <55 lb**; re-optimize hardware or plan appropriate regulatory pathway.
- [ ] Ground-bench and representative hover-flight test with logged current, voltage, air temperatures and demonstrated conservative reserve under safe test conditions.
- [ ] Verify long-range zoom usefulness and acceptable wildlife observation distances; evaluate noise, species, permits and disturbance risk.

**Purchase gate remains CLOSED** until critical compatibility, structure/CG, mass, power and operating-safety issues are resolved.

## Source specifications

1. EFT E6 series: https://effort-tech.com/en/e6
2. EFT E4P/E6P engineering specs: https://www.effort-tech.com/enm/eps
3. Gremsy T7 limits: https://docs.gremsy.com/gimbals/gremsy-t7/general
4. Gremsy T7 official model: https://gremsy.com/products/gremsy-t7
5. Sony ILX-LR1 manual: https://helpguide.sony.net/ilc/2390/v1/en/contents/221h_specifications.html
6. Sony ILX-LR1 mounting holes: https://helpguide.sony.net/ilc/2390/v1/en/contents/221h_names_of_parts.html
7. Sony original SEL70200G: https://www.sony.ca/en/electronics/support/lenses-e-mount-lenses/sel70200g/specifications
8. Hobbywing X8 propulsion mass + bench thrust/power curve: https://www.hobbywing.com/en/index.php/products/xrotor-x8108.html
9. Tattu 22Ah 12S 300Wh/kg battery: https://www.tattuworld.com/products/tattu-300wh-kg-22000mah-12s1p-44-4v-10c-semi-solid-state-uav-lipo-battery.html
10. Tattu Neo 12S high-density battery specification: https://www.grepow.com/semi-solid-state-battery/compact-smart-batteries-tattu-neo-series.html
11. Tattu 22Ah conventional smart battery: https://www.tattuworld.com/products/tattu-plus-1-0-22000mah-12s1p-44-4v-25c-smart-uav-lipo-battery-with-as150u-f-plug.html
12. Hesai JT128: https://www.hesaitech.com/product/jt128/
13. Hesai JT128 user manual: https://www.hesaitech.com/wp-content/uploads/2026/04/JT128_User_Manual_J01-en-260330.pdf
14. Luxonis OAK-D Pro W: https://checkout.luxonis.com/products/oak-d-pro-w
15. FLIR Boson+ OEM: https://oem.flir.com/products/boson-plus/
16. NVIDIA Orin NX modes: https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html
17. FAA Part 107: https://www.faa.gov/newsroom/small-unmanned-aircraft-systems-uas-regulations-part-107
