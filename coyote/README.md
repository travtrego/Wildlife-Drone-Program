# Coyote

## Role
Advanced close-range autonomous sensing and multi-sensor robotics platform.

Coyote is the destination for autonomy that has already been proven on the X500 and for perception capabilities that benefit from a larger, more capable aircraft.

## Complete platform report and Claude handoff

- [**Master Engineering Report**](PLATFORM_MASTER_REPORT.md) — full aircraft history, decisions, fixed sensors, proposed placement, camera, mass, power, integration and procurement blockers.
- [**Engineering Feasibility v0.1**](ENGINEERING_FEASIBILITY.md) — published/estimated inputs and illustrative battery/endurance budgets.
- [**Claude independent review request**](CLAUDE_REVIEW_REQUEST.md) and [**repository Claude Code instructions**](../CLAUDE.md) — ready for a second-opinion review; **not yet executed**.

## Current architecture direction
- EFT E616P folding hexacopter frame selected as the Coyote airframe candidate (not yet engineering-frozen or purchased)
- Pixhawk 6X-class flight controller
- Jetson Orin NX 16 GB-class companion computer
- RTK GNSS
- high-bandwidth IP data link plus independent flight telemetry/control path
- Sony ILX-LR1 + SEL70200G 70–200mm F4 lens + Gremsy T7 proposed for long-range wildlife imaging; pending physical/electrical approval
- OAK-D Pro W class depth / machine-vision sensor
- Hesai JT128-class perception LiDAR candidate
- permanently mounted thermal payload (model to be selected)

## Airframe selection — EFT E616P (selected, pending validation)
- **User-selected platform:** EFT E616P, six-rotor folding industrial/agricultural frame.
- **Decision status:** selected for Coyote's engineering baseline, **NOT** approved for procurement until integration and performance checks pass.
- **Manufacturer frame mass:** approximately 6.41 kg; **wheelbase:** approximately 1644–1648 mm (manufacturer pages differ).
- **Manufacturer propulsion reference, not a purchase list:** X8 motor class, 30-inch propellers, 12S power, 22 Ah battery class. Final motors, ESCs, battery count/capacity and props are **unselected** pending thrust/endurance analysis.
- **Manufacturer's nominal load classification:** 16 kg class, which is *not* a verified payload rating for our camera/LiDAR configuration.
- **Envelope:** manufacturer pages give differing unfolded dimensions (some reference ~2429 x 1733 x 599 mm; another ~2429 x 2429 x 599 mm). Confirm the current revision's dimensioned drawings and actual rotor clearance before physical layout.
- **Frame integration requirements:** measure electronics compartment and mounts, confirm payload mounting interface under the center body, gimbal ground/landing gear clearance, OAK-D / LiDAR / RTK line-of-sight, cooling/weather protection, battery compartment and CG adjustment, EMI/radio isolation, and vibration damping.
- **Procurement gate:** verified manufacturer drawing/manual and SKU; mass, center of gravity and thrust margins with installed payloads; endurance/power budget; cooling and mounting plan. No frame or propulsion purchase recommended until then.

Manufacturer references:
- https://www.effort-tech.com/enm/e6
- https://www.effort-tech.com/en/eps
- https://www.effort-tech.com/en/e616p

## Fixed, integrated payload architecture (owner decision, 2026-10-14)
- **No mission-by-mission payload swapping.** Coyote must carry its full research sensor suite permanently, with secure mounts, wiring, calibration, and repeatable alignment.
- The integrated sensor baseline consists of Sony ILX-LR1 + stabilized gimbal, modular-thermal concept upgraded to a **permanently mounted thermal sensor** (specific FLIR model still to be selected), OAK-D Pro W-class depth/vision sensor, Hesai JT128-class LiDAR candidate, RTK GNSS, Jetson Orin NX-class compute, and Pixhawk 6X-class flight controller.
- Although sensors may be selectively powered or used during missions, **mechanical configuration stays fixed**.
- Do **not** solve payload or endurance shortfalls by removing or swapping sensors; instead rework packaging, power, propulsion, endurance goals, or frame choice.
- Design the aircraft around the **simultaneous installed mass** and conservative concurrent power/heat estimates (not the mass of a single sensor package).
- Before clearing the selected EFT E616P for purchase, verify fixed mounts, weather/vibration protection, gimbal/landing-gear clearance, all camera/LiDAR fields of view, CG, rotor disk spacing, wiring, EMI/RF, cooling, thrust margin, mission endurance, and applicable aircraft-weight limits.
- A fixed payload is a mechanical requirement, **not** a claim that all currently proposed hardware has been proven compatible.

## Sony wildlife imaging subsystem — preferred engineering pairing (2026-10-15)
**Status:** proposed component pairing for engineering validation. Do not purchase until the vendor-confirmed physical, electronic, and flight-integration gates below pass. Coyote retains its permanent, non-swappable sensor payload design.

| Component | Candidate | Reference mass | Key reason |
| --- | --- | ---: | --- |
| RGB camera | Sony ILX-LR1, 61 MP full frame | 243 g | High-resolution wildlife images and mapping |
| Lens | Sony FE 70–200mm F4 G OSS, original SEL70200G | 840 g, excludes tripod mount | 70–200 mm focal range, **constant barrel length** through zoom; 80 × 175 mm |
| Gimbal | Gremsy T7 3-axis | 1,860 g | ~3,175 g gimbal *payload* rating and larger cage; unlike Pixy LR, intended for heavy/custom cameras |
| **Subtotal** | Camera + lens + gimbal | **2,943 g** | Excludes hood, lens collar, balance weights, adapters, mounting, damping, cables, power electronics and zoom actuation |

### Rejected or backup camera approaches
- **Gremsy Pixy LR + Sony FE 85mm F1.8:** officially listed as compatible, and ~1,109 g nominal for lens + camera + gimbal; however 85 mm is limited for distant birds/animal identification, and Gremsy labels the 85 mm combination as *photography only*. Retain solely as a lower-mass fallback.
- **Sony SEL70200G2 70–200mm F4 Macro G OSS II:** nominally lighter (794 g) but extends in length while zooming, making constant gimbal balance and obstacle clearance harder. Do not silently substitute for **SEL70200G**.
- **T3V3 and other smaller cages:** the published weight rating alone does not establish balancing space with the proposed long lens. T7 preferred pending full dimensional check.

### Optical rationale and limitations
- Sony ILX-LR1 is ~9504 pixels across a 35.7 mm wide sensor. In an ideal pinhole approximation, a 30 cm subject at 200 m projects about 34 px at 85 mm, 54 px at 135 mm, and 80 px at 200 mm. These are geometric *upper bounds*, not a guaranteed identification range; sharpness, motion, atmospheric conditions, illumination, subject orientation, and ethical wildlife stand-off distances affect results.
- **Remote zoom is not implemented by merely mounting SEL70200G.** Zoom is mechanically controlled, and a custom lens-ring actuator or proven commercial zoom drive plus control and balance testing would be required for in-flight optical zoom. A fixed initial focal setting is a fallback only; non-swappable sensors does not prohibit software-controlled zoom.
- The Sony ILX-LR1 can record still images and movies, but correct onboard control/data interfaces must be integrated and verified independently of gimbal stabilization.

### Required acceptance gates, all open
- [ ] Obtain Gremsy written confirmation or bench proof that T7 cage, axes and balance range fit the **exact ILX-LR1 + SEL70200G** combination, including lens collar, camera body, HDMI/USB/power cables, filter/hood and full articulation; T7's camera list does **not** explicitly certify this combination.
- [ ] Validate Sony ILX-LR1 lens electrical / AF / exposure compatibility and separate camera power, trigger, image transfer and video link; T7 gimbal stabilization alone is not a Sony camera integration kit.
- [ ] Design, source, and bench-test the zoom ring drive, or formally document the restricted fixed focal-length initial configuration.
- [ ] CAD model total pan/tilt roll sweep against E616P landing gear, rotors and payload mounts; measure ground clearance during landing.
- [ ] Include minimum 2.943 kg camera system plus all ancillary hardware in permanent-installed full-aircraft mass and CG model; compared with Pixy LR + 85mm (~1.109 kg), ~1.834 kg extra before mounts.
- [ ] Evaluate vibration isolation, wind load, thermal limits, environmental protection and camera pointing calibration.
- [ ] Recalculate 25–30 minute mission goal, thrust margin and applicable aircraft-weight limits with all permanent sensors installed.

### Technical references
- https://docs.gremsy.com/gimbals/pixy-lr/faq
- https://gremsy.com/products/gremsy-t7
- https://docs.gremsy.com/gimbals/gremsy-t7/general
- https://www.sony.ca/en/electronics/support/lenses-e-mount-lenses/sel70200g/specifications
- https://www.sony.com/electronics/support/camcorders-and-video-cameras-interchangeable-lens-camcorders/ilx-lr1

## Engineering feasibility v0.1 (2026-10-15)
**[Read the camera fit, installed mass, battery, hover-power and sensor layout feasibility report](ENGINEERING_FEASIBILITY.md).**

- **Gremsy T7 + ILX-LR1 + original SEL70200G:** camera+glass mass meets T7 payload rating, but gimbal envelope, actual CG balance, in-flight optical zoom and gimbal travel remain **unverified**. Do not buy based on payload mass rating alone.
- **E616P preliminary 12S weight model:** approximately **23.78 kg** with the reference six Hobbywing X8 propulsion units and a 3.421 kg Tattu 22Ah 12S example, with 1.17 kg margin below the US 55 lb small-UAS limit. All other unselected subsystems include placeholders, so this is NOT a frozen takeoff weight.
- **Nominal idealized endurance screening:** about **19.9 min** (22Ah light battery), **22.6 min** (26Ah) and **27.4 min** (33Ah); the 33Ah option exceeds the 55 lb threshold in the current model. Calculations are bench-power estimates, not operational flight-time guarantees.
- Battery discharge-current and vendor-controlled fit documentation are open **purchase blockers**; no purchase approvals have been granted.
- Permanently installed sensor requirements stay unchanged. If this aircraft cannot satisfy required mass, energy or optical geometry, reevaluate power, packaging, propulsion or frame before compromising the mission.

## Design rules
1. Do not duplicate safety-critical control on the Jetson.
2. Keep Pixhawk near true CG and mechanically isolated.
3. Keep compute thermally managed and electrically separated from sensitive navigation hardware.
4. Treat battery placement as a CG-trim tool.
5. Prove every autonomy behavior on a lower-risk platform or in simulation before promotion.
6. Do not add payload merely because capacity exists; every sensor must justify mass, power, drag, thermal load, and integration cost.

## Software inheritance
Coyote should reuse stable modules from `shared/` for mission management, telemetry, logging, safety interfaces, and common message definitions. Coyote-specific work should focus on richer perception, sensor fusion, obstacle understanding, and local autonomous decision-making.
