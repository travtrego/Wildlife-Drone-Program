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
