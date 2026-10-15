# Coyote

## Role
Advanced close-range autonomous sensing and multi-sensor robotics platform.

Coyote is the destination for autonomy that has already been proven on the X500 and for perception capabilities that benefit from a larger, more capable aircraft.

## Current architecture direction
- EFT E616P folding hexacopter frame selected as the Coyote airframe candidate (not yet engineering-frozen or purchased)
- Pixhawk 6X-class flight controller
- Jetson Orin NX 16 GB-class companion computer
- RTK GNSS
- high-bandwidth IP data link plus independent flight telemetry/control path
- Sony ILX-LR1 + stabilized gimbal class RGB payload
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

## Design rules
1. Do not duplicate safety-critical control on the Jetson.
2. Keep Pixhawk near true CG and mechanically isolated.
3. Keep compute thermally managed and electrically separated from sensitive navigation hardware.
4. Treat battery placement as a CG-trim tool.
5. Prove every autonomy behavior on a lower-risk platform or in simulation before promotion.
6. Do not add payload merely because capacity exists; every sensor must justify mass, power, drag, thermal load, and integration cost.

## Software inheritance
Coyote should reuse stable modules from `shared/` for mission management, telemetry, logging, safety interfaces, and common message definitions. Coyote-specific work should focus on richer perception, sensor fusion, obstacle understanding, and local autonomous decision-making.
