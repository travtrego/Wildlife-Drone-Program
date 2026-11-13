"""Real-X500 settings profile: **unfilled model inputs**, separate from SITL.

The SITL placeholders stay in ``settings.py`` and ``monitor_settings.py`` and
are not copied here. Every real-X500 value below is deliberately empty: it is
filled in only from an owner choice, bench record or logged manual flight of
the assembled X500 (issue #1), each with a reference. Until then
``build_flight_settings(X500_REAL_INPUTS)`` refuses and lists every missing
input. No code path uses this profile yet; connecting to the real aircraft is
an owner decision and is not implemented.
"""

from __future__ import annotations

from .aircraft_profile import ModelInput

# Reference facts, not profile inputs (never read by code).
# - Battery: owner bought 4S 5500 mAh LiPo packs (stated 2026-11-12). Mass,
#   internal resistance and usable capacity on this airframe are unmeasured.
# - Holybro catalogue claim: about 18 min hover on a 5000 mAh pack with no
#   payload. A catalogue claim is not accepted for usable_flight_time_s.
X500_BATTERY_PACK_NOTE = "4S 5500 mAh LiPo (owner purchase); not characterised on the X500"
X500_CATALOGUE_HOVER_CLAIM_MIN = 18.0  # catalogue claim, 5000 mAh, no payload

X500_REAL_INPUTS: dict[str, ModelInput] = {
    "max_relative_altitude_m": ModelInput(
        note="Owner choice; at or below the GF_MAX_VER_DIST set on the X500's PX4."
    ),
    "min_waypoint_altitude_m": ModelInput(
        note="Owner choice; clearance above obstacles at the test field."
    ),
    "max_distance_from_home_m": ModelInput(
        note="Owner choice; at or below GF_MAX_HOR_DIST and within visual line of sight."
    ),
    "max_speed_m_s": ModelInput(
        note="Owner choice; at or below MPC_XY_VEL_MAX, informed by manual-flight handling."
    ),
    "max_waypoints": ModelInput(note="Owner choice (SITL uses 20)."),
    "min_battery_fraction": ModelInput(
        note=(
            "Owner choice at or above BAT_LOW_THR. SITL uses the owner's 40 % of "
            "2026-10-31; whether it carries over to the real X500 is not decided."
        )
    ),
    "max_telemetry_age_s": ModelInput(
        note="Largest mode/armed/in_air stream gap seen over the real telemetry link, plus margin."
    ),
    "start_timeout_s": ModelInput(
        note="Logged time from start_mission request to armed MISSION mode reported."
    ),
    "max_item_time_s": ModelInput(
        note="Longest logged item time incl. takeoff climb, plus margin, for the test missions."
    ),
    "max_mission_time_s": ModelInput(
        note="Logged mission time for the planned missions, plus margin."
    ),
    "completion_grace_s": ModelInput(
        note="Logged HOLD-before-final-progress delay (seen in SITL, never measured)."
    ),
    "accept_timeout_s": ModelInput(note="Logged RTL request -> RETURN_TO_LAUNCH reported."),
    "max_return_time_s": ModelInput(
        note="Logged RTL request -> landed and disarmed from the farthest planned point."
    ),
    "disarm_timeout_s": ModelInput(
        note="Logged landed -> disarmed (PX4 COM_DISARM_LAND on the X500), plus margin."
    ),
    "usable_flight_time_s": ModelInput(
        note=(
            "Logged takeoff -> landing battery reserve with the 4S 5500 mAh pack and "
            "flight configuration. Not the catalogue hover claim."
        )
    ),
}
