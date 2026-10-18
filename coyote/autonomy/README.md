# Coyote companion-side autonomy

Jetson-side code that **requests** mission actions. PX4/Pixhawk keeps stabilization, geofence, battery and link-loss failsafes, RTL and pilot override.

## `action_gate.py`

Deterministic, dependency-free gate that decides whether the companion computer may forward a proposed action (`HOLD`, `GOTO_LOCAL`, `RETURN_TO_LAUNCH`, `LAND`) to PX4, given the latest telemetry snapshot. Checks run in a fixed order:

1. Stale or invalid telemetry → reject everything (PX4 link-loss failsafe owns the aircraft).
2. Pilot-controlled PX4 mode (`MANUAL`, `STABILIZED`, `ALTCTL`, `POSCTL`, `ACRO`, `RATTITUDE`) → reject everything; the companion yields.
3. PX4 recovery mode (`RETURN_TO_LAUNCH`, `LAND`) → reject everything; never fight RTL or a failsafe.
4. Mode not in `HOLD`/`MISSION`/`OFFBOARD`, or no explicit operator delegation → reject.
5. Not armed and airborne → reject (arming/takeoff stay with the operator and PX4).
6. De-escalating actions (`HOLD`, `RETURN_TO_LAUNCH`, `LAND`) → allow.
7. `GOTO_LOCAL` → allow only inside the advisory altitude band and home radius and above the advisory battery reserve; otherwise reject with a *recommended* action (`HOLD` or `RETURN_TO_LAUNCH`) that the gate never issues itself.

### Evidence status

- **Unit-tested only** (`tests/test_coyote_action_gate.py`). Not yet wired to MAVSDK, not run in PX4 SITL, not bench- or flight-tested.
- `AdvisoryLimits` defaults (60 m ceiling, 5 m floor, 150 m radius, 40 % goto reserve, 1 s telemetry age) are **model inputs / development placeholders**, not a validated Coyote envelope. They must be configured inside, never looser than, the PX4 geofence and battery failsafe parameters.
- How `operator_delegated` is sourced (RC aux switch, GCS command, or other) is an **open owner/design decision**. PX4 flight mode alone cannot prove delegation — for example `HOLD` can be pilot- or failsafe-selected.
- This gate does not implement wildlife stand-off distances, obstacle avoidance or animal identification.
