"""Deterministic Fighter VTOL survey plan: VTOL takeoff, fixed-wing lines, VTOL landing.

The companion computer (or a ground-side planning tool) uses this module to turn
a rectangular survey area into an ordered list of *proposed* mission items:

    VTOL takeoff -> transition to fixed-wing -> survey lines -> approach
    -> transition to multicopter -> VTOL landing at home

It does not command anything. PX4 still owns VTOL transitions, fixed-wing
guidance, stabilization, geofence, battery/link failsafes, RTL and pilot
override; a later MAVSDK adapter would map these items to PX4 mission items
(for example MAVSDK ``MissionItem.vehicle_action`` TRANSITION_TO_FW/MC) only
after this plan has been checked.

What the planner guarantees (as calculations, not flight evidence)
------------------------------------------------------------------
* Every turn between survey lines is a 180-degree turn whose lateral offset is
  at least twice the modeled minimum fixed-wing turn radius. When the requested
  line spacing is tighter than that, lines are flown in interleaved passes
  (0, g, 2g, ..., then 1, 1+g, ...) instead of rejecting the area outright.
* Each line has a lead-in and run-out of one turn radius so the aircraft is
  modeled as aligned before the line starts.
* Every fixed-wing point, padded by one turn radius for turn overshoot, stays
  inside an advisory distance from home that must be set inside the PX4
  geofence.
* There is modeled room for the forward transition before the first line and
  a straight inbound leg before the back transition.

Hardware numbers in :class:`FighterModelInputs` are MODEL INPUTS / PLACEHOLDERS.
They are not measured from the owner's Fighter airframe, not PX4 parameters read
from an autopilot and not flight-test results. Wind, climb performance, terrain,
obstacles and battery energy are not modeled.

Coordinates are local metres relative to PX4 home: ``north_m``, ``east_m`` and
``altitude_m`` above home (positive up).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

GRAVITY_M_S2 = 9.80665
# Planner refuses more lines than this to keep plans reviewable and bounded.
MAX_SURVEY_LINES = 200
_TOLERANCE_M = 1e-6


class SurveyPlanError(ValueError):
    """The survey cannot be planned within the model inputs and advisory limits."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(reasons))


class Phase(Enum):
    VTOL_TAKEOFF = "vtol_takeoff"
    TRANSITION_TO_FW = "transition_to_fw"
    FW_WAYPOINT = "fw_waypoint"
    TRANSITION_TO_MC = "transition_to_mc"
    VTOL_LAND = "vtol_land"


@dataclass(frozen=True)
class FighterModelInputs:
    """Airframe performance values used by the planner.

    MODEL INPUTS / PLACEHOLDERS. None of these are measured on the Fighter 2430
    or read from its PX4 configuration. Replace them with values derived from
    the configured PX4 parameters (for example trim airspeed and roll limit)
    and logged SITL/flight transitions before relying on a plan.
    """

    cruise_airspeed_m_s: float = 18.0
    # Bank used for planning turns; keep it below the PX4 fixed-wing roll limit
    # so the planned radius is achievable with margin.
    planning_bank_deg: float = 30.0
    # Ground distance from transition start to stable fixed-wing flight.
    forward_transition_distance_m: float = 250.0
    # Ground distance from back-transition start to multicopter hover.
    back_transition_distance_m: float = 200.0

    def validate(self) -> None:
        values = (
            self.cruise_airspeed_m_s,
            self.planning_bank_deg,
            self.forward_transition_distance_m,
            self.back_transition_distance_m,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Fighter model inputs must be finite numbers")
        if self.cruise_airspeed_m_s <= 0.0:
            raise ValueError("cruise_airspeed_m_s must be positive")
        if not 5.0 <= self.planning_bank_deg <= 45.0:
            raise ValueError("planning_bank_deg must be between 5 and 45 degrees")
        if self.forward_transition_distance_m <= 0.0 or self.back_transition_distance_m <= 0.0:
            raise ValueError("transition distances must be positive")

    @property
    def min_turn_radius_m(self) -> float:
        """Coordinated-turn radius r = V^2 / (g tan(bank)), still air."""

        bank = math.radians(self.planning_bank_deg)
        return self.cruise_airspeed_m_s**2 / (GRAVITY_M_S2 * math.tan(bank))


@dataclass(frozen=True)
class SurveyLimits:
    """Companion-side advisory limits for a survey plan.

    DEVELOPMENT PLACEHOLDERS. They must sit inside (never looser than) the PX4
    geofence, altitude and failsafe configuration, which remain authoritative.
    """

    # VTOL climb height at which forward/back transitions are requested; must
    # be at or above the fixed-wing floor because transitions end/begin in
    # fixed-wing flight.
    transition_altitude_m: float = 40.0
    survey_altitude_m: float = 80.0
    min_fixed_wing_altitude_m: float = 40.0
    max_altitude_m: float = 120.0
    max_distance_from_home_m: float = 1500.0

    def validate(self) -> None:
        values = (
            self.transition_altitude_m,
            self.survey_altitude_m,
            self.min_fixed_wing_altitude_m,
            self.max_altitude_m,
            self.max_distance_from_home_m,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Survey limits must be finite numbers")
        if self.max_altitude_m > 120.0:
            # Stay at or below the ~400 ft AGL Part 107 ceiling by default.
            raise ValueError("max_altitude_m above 120 m is not allowed by this planner")
        if self.transition_altitude_m <= 0.0:
            raise ValueError("transition_altitude_m must be positive")
        if not (self.min_fixed_wing_altitude_m <= self.survey_altitude_m <= self.max_altitude_m):
            raise ValueError(
                "Require min_fixed_wing_altitude_m <= survey_altitude_m <= max_altitude_m"
            )
        if not (
            self.min_fixed_wing_altitude_m <= self.transition_altitude_m <= self.max_altitude_m
        ):
            raise ValueError(
                "Require min_fixed_wing_altitude_m <= transition_altitude_m <= max_altitude_m"
            )
        if self.max_distance_from_home_m <= 0.0:
            raise ValueError("max_distance_from_home_m must be positive")


@dataclass(frozen=True)
class SurveyArea:
    """Rectangle of parallel survey lines.

    Line 0 starts at (``start_north_m``, ``start_east_m``) and runs
    ``line_length_m`` along ``line_heading_deg`` (0 = north, 90 = east).
    Further lines are offset to the right of that heading every
    ``line_spacing_m`` until ``cross_track_width_m`` is covered; the last line
    may lie up to one spacing beyond the width so the edge is covered.
    """

    start_north_m: float
    start_east_m: float
    line_heading_deg: float
    line_length_m: float
    cross_track_width_m: float
    line_spacing_m: float

    def validate(self) -> None:
        values = (
            self.start_north_m,
            self.start_east_m,
            self.line_heading_deg,
            self.line_length_m,
            self.cross_track_width_m,
            self.line_spacing_m,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Survey area values must be finite numbers")
        if self.line_length_m <= 0.0:
            raise ValueError("line_length_m must be positive")
        if self.cross_track_width_m < 0.0:
            raise ValueError("cross_track_width_m must not be negative")
        if self.line_spacing_m <= 0.0:
            raise ValueError("line_spacing_m must be positive")

    @property
    def line_count(self) -> int:
        return math.ceil(self.cross_track_width_m / self.line_spacing_m - 1e-9) + 1


@dataclass(frozen=True)
class PlanItem:
    phase: Phase
    north_m: float
    east_m: float
    altitude_m: float
    role: str
    line_index: int | None = None


@dataclass(frozen=True)
class SurveyPlan:
    items: tuple[PlanItem, ...]
    line_order: tuple[int, ...]
    line_interleave: int
    turn_radius_m: float


def interleaved_line_order(line_count: int, interleave: int) -> tuple[int, ...]:
    """Fly lines in passes 0, g, 2g, ... then 1, 1+g, ... (g = ``interleave``).

    With ``interleave`` 1 this is an ordinary back-and-forth (boustrophedon)
    order. Consecutive lines in the returned order are not guaranteed to be
    ``interleave`` apart at pass boundaries; :func:`plan_survey` checks that.
    """

    if line_count < 1 or interleave < 1:
        raise ValueError("line_count and interleave must be at least 1")
    order: list[int] = []
    for first in range(min(interleave, line_count)):
        order.extend(range(first, line_count, interleave))
    return tuple(order)


def plan_survey(
    area: SurveyArea,
    model: FighterModelInputs | None = None,
    limits: SurveyLimits | None = None,
) -> SurveyPlan:
    """Return an ordered VTOL survey plan or raise :class:`SurveyPlanError`."""

    model = model or FighterModelInputs()
    limits = limits or SurveyLimits()
    model.validate()
    limits.validate()
    area.validate()

    radius = model.min_turn_radius_m
    line_count = area.line_count
    if line_count > MAX_SURVEY_LINES:
        raise SurveyPlanError(
            [f"{line_count} survey lines exceeds planner limit {MAX_SURVEY_LINES}"]
        )

    # Smallest line skip whose lateral offset allows a 180-degree turn.
    interleave = max(1, math.ceil(2.0 * radius / area.line_spacing_m - 1e-9))
    order = interleaved_line_order(line_count, interleave)

    reasons: list[str] = []
    for previous, current in zip(order, order[1:], strict=False):
        offset = abs(current - previous) * area.line_spacing_m
        if offset + _TOLERANCE_M < 2.0 * radius:
            reasons.append(
                f"turn from line {previous} to line {current} offsets {offset:.1f} m, "
                f"below 2 x turn radius {2.0 * radius:.1f} m (widen the area, "
                "increase spacing or lower the planning airspeed)"
            )
            break

    heading = math.radians(area.line_heading_deg)
    along = (math.cos(heading), math.sin(heading))
    right = (-math.sin(heading), math.cos(heading))

    def point(line: int, along_m: float) -> tuple[float, float]:
        offset = line * area.line_spacing_m
        return (
            area.start_north_m + along_m * along[0] + offset * right[0],
            area.start_east_m + along_m * along[1] + offset * right[1],
        )

    alt = limits.survey_altitude_m
    survey: list[PlanItem] = []
    for flown, line in enumerate(order):
        if flown % 2 == 0:
            sequence = (-radius, 0.0, area.line_length_m, area.line_length_m + radius)
        else:
            sequence = (area.line_length_m + radius, area.line_length_m, 0.0, -radius)
        for role, along_m in zip(
            ("line_entry", "line_start", "line_end", "line_exit"), sequence, strict=True
        ):
            north, east = point(line, along_m)
            survey.append(PlanItem(Phase.FW_WAYPOINT, north, east, alt, role, line))

    first = survey[0]
    first_distance = math.hypot(first.north_m, first.east_m)
    needed = model.forward_transition_distance_m + 2.0 * radius
    if first_distance + _TOLERANCE_M < needed:
        reasons.append(
            f"first line entry is {first_distance:.1f} m from home; forward transition "
            f"plus alignment needs at least {needed:.1f} m"
        )

    last = survey[-1]
    last_distance = math.hypot(last.north_m, last.east_m)
    if last_distance < _TOLERANCE_M:
        bearing = (-along[0], -along[1])
    else:
        bearing = (last.north_m / last_distance, last.east_m / last_distance)
    approach_distance = model.back_transition_distance_m + 2.0 * radius
    back_transition = model.back_transition_distance_m
    approach = PlanItem(
        Phase.FW_WAYPOINT,
        bearing[0] * approach_distance,
        bearing[1] * approach_distance,
        limits.transition_altitude_m,
        "approach",
    )
    to_mc = PlanItem(
        Phase.TRANSITION_TO_MC,
        bearing[0] * back_transition,
        bearing[1] * back_transition,
        limits.transition_altitude_m,
        "back_transition_start",
    )

    for item in (*survey, approach):
        padded = math.hypot(item.north_m, item.east_m) + radius
        if padded > limits.max_distance_from_home_m + _TOLERANCE_M:
            reasons.append(
                f"{item.role} (line {item.line_index}) plus turn radius reaches "
                f"{padded:.1f} m from home, beyond advisory "
                f"{limits.max_distance_from_home_m:.1f} m"
            )
            break

    if reasons:
        raise SurveyPlanError(reasons)

    items = (
        PlanItem(Phase.VTOL_TAKEOFF, 0.0, 0.0, limits.transition_altitude_m, "takeoff"),
        PlanItem(
            Phase.TRANSITION_TO_FW,
            0.0,
            0.0,
            limits.transition_altitude_m,
            "forward_transition_toward_first_line",
        ),
        *survey,
        approach,
        to_mc,
        PlanItem(Phase.VTOL_LAND, 0.0, 0.0, 0.0, "land_at_home"),
    )
    return SurveyPlan(items, order, interleave, radius)
