"""X500 SITL timing inputs for :mod:`x500.flight.mission_monitor`.

MODEL INPUTS / SITL DEVELOPMENT PLACEHOLDERS. None of these numbers is an X500
measurement, a PX4 parameter or a validated envelope. They are sized for short
SITL missions (tens of metres between items at a few m/s) and must be revised
from logged SITL runs, then from controlled X500 flights, before any use beyond
simulation. Coyote will pass its own values to the same monitor.
"""

from __future__ import annotations

from .mission_monitor import MonitorSettings
from .return_monitor import ReturnSettings


def x500_sitl_monitor_settings(expected_item_count: int) -> MonitorSettings:
    """Return validated X500 SITL placeholder settings for a mission of N items."""

    settings = MonitorSettings(
        expected_item_count=expected_item_count,
        start_timeout_s=10.0,  # placeholder: start ack -> armed MISSION mode reported
        max_item_time_s=60.0,  # placeholder: per-item budget incl. takeoff climb
        max_mission_time_s=300.0,  # placeholder: whole mission, well under SITL battery
        max_telemetry_age_s=2.0,  # placeholder: companion-side silence before giving up
        # placeholder: PX4 reported HOLD before final-item progress in SITL on
        # 2026-11-01; allow ~3 progress updates at the observed 1 Hz telemetry
        completion_grace_s=3.0,
    )
    settings.validate()
    return settings


# Return/landing watch after the RTL request (x500.flight.return_monitor).
# Placeholders, not measurements or PX4 parameters. PX4 is expected to disarm
# on its own after landing (COM_DISARM_LAND); that parameter is not read here
# and the disarm delay has not been observed in SITL.
X500_SITL_RETURN_SETTINGS = ReturnSettings(
    accept_timeout_s=5.0,  # placeholder: ~5 flight-mode updates at the observed 1 Hz
    max_return_time_s=120.0,  # placeholder: the former landing timeout of the SITL script
    disarm_timeout_s=10.0,  # placeholder: landed -> disarmed
    max_telemetry_age_s=2.0,  # placeholder: same as the mission monitor
)
X500_SITL_RETURN_SETTINGS.validate()
