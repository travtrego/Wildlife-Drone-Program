# Coyote

## Role
Advanced close-range autonomous sensing and multi-sensor robotics platform.

Coyote is the destination for autonomy that has already been proven on the X500 and for perception capabilities that benefit from a larger, more capable aircraft.

## Current architecture direction
- industrial multirotor frame, final layout still subject to engineering freeze
- Pixhawk 6X-class flight controller
- Jetson Orin NX 16 GB-class companion computer
- RTK GNSS
- high-bandwidth IP data link plus independent flight telemetry/control path
- Sony ILX-LR1 + stabilized gimbal class RGB payload
- OAK-D Pro W class depth / machine-vision sensor
- Hesai JT128-class perception LiDAR candidate
- modular thermal payload

## Design rules
1. Do not duplicate safety-critical control on the Jetson.
2. Keep Pixhawk near true CG and mechanically isolated.
3. Keep compute thermally managed and electrically separated from sensitive navigation hardware.
4. Treat battery placement as a CG-trim tool.
5. Prove every autonomy behavior on a lower-risk platform or in simulation before promotion.
6. Do not add payload merely because capacity exists; every sensor must justify mass, power, drag, thermal load, and integration cost.

## Software inheritance
Coyote should reuse stable modules from `shared/` for mission management, telemetry, logging, safety interfaces, and common message definitions. Coyote-specific work should focus on richer perception, sensor fusion, obstacle understanding, and local autonomous decision-making.
