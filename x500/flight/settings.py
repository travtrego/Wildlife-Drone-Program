"""X500 per-aircraft settings for the multirotor flight layer.

**Model inputs / development placeholders.** None of these numbers is a
measurement of the X500 or a tuned PX4 parameter. They are deliberately small
for PX4 SITL development and must be set inside, never looser than, the PX4
geofence and failsafe parameters before any use beyond simulation. Coyote will
pass its own limits to the same code.
"""

from __future__ import annotations

from x500.flight.preflight import PreflightLimits
from x500.flight.waypoint_mission import MultirotorMissionLimits

X500_SITL_MISSION_LIMITS = MultirotorMissionLimits(
    max_relative_altitude_m=30.0,
    min_waypoint_altitude_m=3.0,
    max_distance_from_home_m=100.0,
    max_speed_m_s=5.0,
    max_waypoints=20,
)

# Companion-side readiness gate before upload/arm (x500.flight.preflight).
# Placeholders: 60 % is not a reserve calculation; it must stay at or above the
# PX4 battery failsafe thresholds. How the PX4 SITL battery simulator reports
# charge while disarmed (SIM_BAT_* parameters) is unobserved here.
X500_SITL_PREFLIGHT_LIMITS = PreflightLimits(
    min_battery_fraction=0.6,
    max_telemetry_age_s=2.0,
)
X500_SITL_PREFLIGHT_LIMITS.validate()
