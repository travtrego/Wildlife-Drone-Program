# Coyote companion-side autonomy

Jetson-side code that **requests** mission actions. PX4/Pixhawk keeps stabilization, geofence, battery and link-loss failsafes, RTL and pilot override.

## `telemetry.py`

Dependency-free adapter between per-stream PX4 telemetry (as MAVSDK delivers it) and the gate. `TelemetryTracker` takes flight mode, armed, in-air, relative altitude and battery updates with monotonic timestamps and builds one `VehicleSnapshot` whose `telemetry_age_s` is the age of the **oldest** stream, so one silent stream makes the whole snapshot stale. A missing or malformed stream makes the age infinite (rejected). MAVSDK 3.x `remaining_percent` (0–100) is converted to the gate's 0.0–1.0 fraction here; out-of-range or non-finite values become unknown, never clamped. Out-of-order updates are dropped. `failsafe_active` is a separate input whose MAVLink source is still unchosen: until something reports it, or once it is older than 1 s (placeholder), it is `None` and the delegation authority refuses or revokes. `observe_vehicle` / `evaluate_companion_request` chain tracker → `DelegationAuthority` → `evaluate_request`; they send nothing to PX4.

Evidence status: **unit-tested only** (`tests/test_coyote_telemetry.py`) against plain values and a stand-in enum; no MAVSDK subscription task, SITL, bench or flight testing exists.

## `delegation.py`

Deterministic state machine that produces the gate's `operator_delegated` flag from R6 (owner decision 2026-10-18; see [DECISIONS.md](../DECISIONS.md) once PR #9 merges). A ground-station grant (with a strictly increasing sequence number, at most 2 s old) is accepted on the ground before takeoff (owner decision 2026-10-20) or in the air, while the latest observation is fresh, failsafe-free and not in a pilot or PX4 recovery mode. A ground grant never lets the companion arm. Once the operator has armed, the gate allows a companion `TAKEOFF` request (owner decision 2026-10-20, option 1); every other request still requires armed and airborne. Any PX4 failsafe, unknown failsafe state, telemetry/observation gap over 1 s, pilot mode, RTL/LAND, disarm after the grant, landing after flying under the grant, bad clock or operator revoke clears it, so one grant covers at most one flight. Revocation is sticky: only a new grant restores it. Each revocation queues one `RevocationAlert` (reason, detail, time) for the ground station; delivery is the future adapter's job.

Evidence status: **unit-tested only** (`tests/test_coyote_delegation.py`). The 1 s / 2 s timings are development placeholders. The MAVLink source for `failsafe_active` and the grant command transport are not chosen; no MAVSDK wiring, SITL, bench or flight testing exists.

## `ground_alerts.py`

R6 requires the ground station to tell the operator, with the reason, whenever delegation is revoked. `DelegationAuthority.drain_alerts()` empties its queue, and revocations cluster around link failures, so draining straight into a send that fails would lose the alert. `GroundAlertOutbox` takes drained alerts and keeps each one, in revocation order, until the sender reports success; a failed send (False or an exception) leaves it at the head and waits `retry_interval_s` (placeholder 0.5 s) before retrying. The queue is bounded (`max_pending`, placeholder 16): overflow drops the oldest alert not currently being sent and sends a "N AUTONOMY ALERTS DROPPED" line first, so loss is visible. `format_status_text` produces an ASCII line of at most 50 characters (MAVLink `STATUSTEXT` size) such as `COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST`, with a severity whose names match MAVSDK `server_utility.StatusTextType` (PX4 failsafe CRITICAL; operator revoke NOTICE; end of flight INFO; everything else WARNING). The full `detail` string stays in the local record. Transport is injected: `deliver(send, now)` for a synchronous sender, or `next_message` / `mark_sent` / `mark_failed` for an async MAVSDK task. "Sent" means the transport accepted it, not that the operator saw it; no ground-station acknowledgement is defined. Delivering an alert never restores delegation.

Evidence status: **unit-tested only** (`tests/test_coyote_ground_alerts.py`). STATUSTEXT as the delivery path is an implementation choice; whether QGroundControl shows a companion-originated STATUSTEXT, and from which MAVLink component, is not observed. No MAVSDK task, SITL, bench or flight testing exists.

## `action_gate.py`

Deterministic, dependency-free gate that decides whether the companion computer may forward a proposed action (`HOLD`, `GOTO_LOCAL`, `RETURN_TO_LAUNCH`, `LAND`) to PX4, given the latest telemetry snapshot. Checks run in a fixed order:

1. Stale or invalid telemetry → reject everything (PX4 link-loss failsafe owns the aircraft).
2. Pilot-controlled PX4 mode (`MANUAL`, `STABILIZED`, `ALTCTL`, `POSCTL`, `ACRO`, `RATTITUDE`) → reject everything; the companion yields.
3. PX4 recovery mode (`RETURN_TO_LAUNCH`, `LAND`) → reject everything; never fight RTL or a failsafe.
4. Mode not in `HOLD`/`MISSION`/`OFFBOARD`, or no explicit operator delegation → reject.
5. `TAKEOFF` (owner decision 2026-10-20, operator on site): allowed only when armed by the operator, on the ground, delegated, in `HOLD`/`MISSION`, battery known and at or above the takeoff reserve (placeholder 80%), and climb altitude inside the advisory limits. The companion never arms; there is no arm action.
6. Any other action when not armed and airborne → reject.
7. De-escalating actions (`HOLD`, `RETURN_TO_LAUNCH`, `LAND`) → allow.
8. `GOTO_LOCAL` → allow only inside the advisory altitude band and home radius and above the advisory battery reserve (battery must be a 0.0–1.0 fraction; values outside that range, such as MAVSDK's 0–100 percent passed straight in, are rejected); otherwise reject with a *recommended* action (`HOLD` or `RETURN_TO_LAUNCH`) that the gate never issues itself.

### Evidence status

- **Unit-tested only** (`tests/test_coyote_action_gate.py`). Not yet wired to MAVSDK, not run in PX4 SITL, not bench- or flight-tested.
- `AdvisoryLimits` defaults (60 m ceiling, 5 m floor, 150 m radius, 40 % goto reserve, 80 % takeoff reserve, 1 s telemetry age) are **model inputs / development placeholders**, not a validated Coyote envelope. They must be configured inside, never looser than, the PX4 geofence and battery failsafe parameters.
- `operator_delegated` will be sourced from a **ground-station command** (owner decision 2026-10-18, [R6](../DECISIONS.md)). The future MAVSDK adapter must clear it on any PX4 failsafe, telemetry-link loss or pilot takeover, require the operator to re-send the command, and notify the ground station with the reason. Not implemented yet. PX4 flight mode alone cannot prove delegation — for example `HOLD` can be pilot- or failsafe-selected.
- This gate does not implement wildlife stand-off distances, obstacle avoidance or animal identification.
