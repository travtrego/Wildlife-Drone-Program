"""Companion-side operator delegation authority for Coyote (requirement R6).

R6 (owner decision 2026-10-18, recorded by PR #9): companion authority is
granted by a ground-station command, is revoked on any PX4 failsafe,
telemetry-link loss or pilot takeover, returns only when the operator re-sends
the command, and the ground station is notified with the reason whenever
authority is revoked.

This module turns that rule into a deterministic state machine whose output is
the ``operator_delegated`` flag consumed by
:func:`coyote.autonomy.action_gate.evaluate_request`. It never commands the
vehicle and never makes PX4 behaviour less conservative.

Design choices (implementation, not new owner requirements)
-----------------------------------------------------------
* **Sticky revocation.** Once revoked, authority stays revoked even if the
  condition clears (link back, pilot hands back, failsafe cleared). Only a
  *new* ground-station grant can restore it.
* **New command only.** Each grant carries a ground-station sequence number;
  a grant whose sequence is not greater than every sequence seen before is
  refused, so a queued or replayed command delivered after a link outage
  cannot silently restore authority. Grants older than
  ``max_grant_age_s`` are refused for the same reason.
* **Unknown is unsafe.** Unknown failsafe state, invalid telemetry age,
  non-finite or backwards clock, or no observation within
  ``max_telemetry_age_s`` all revoke.
* **Grantable before takeoff (owner decision 2026-10-20).** A grant is
  accepted on the ground (armed or disarmed) or in the air, provided the
  latest observation is fresh, failsafe-free and not in a pilot or PX4
  recovery mode. A pilot-controlled ground mode (e.g. POSCTL) still refuses
  the grant, so the operator selects HOLD/MISSION before delegating.
  Granting on the ground does NOT let the companion arm or take off: the
  action gate still rejects every request unless the vehicle is armed and
  airborne. It only removes the need to re-send the command once flying.
* **One flight per grant.** PX4 RTL/LAND (commanded or failsafe) revoke.
  Disarming after a grant (armed -> disarmed) and landing after the vehicle
  has been airborne under this grant (in_air -> on ground) also revoke, so a
  grant never carries over to a second flight. Arming after a disarmed grant
  does not revoke. ``in_air`` while disarmed is treated as invalid input.
* **Alerts are queued, not sent.** Each revocation transition enqueues exactly
  one :class:`RevocationAlert`. The future MAVSDK/GCS adapter drains and
  delivers them; alerts stay queued across a link outage until drained.

Open items: which MAVLink/MAVSDK signal provides ``failsafe_active`` and how
the grant command reaches the Jetson are not chosen yet. Timing defaults are
development placeholders (model inputs), not tested values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum

from coyote.autonomy.action_gate import (
    AUTOPILOT_RECOVERY_MODES,
    PILOT_CONTROLLED_MODES,
    VehicleSnapshot,
)


class RevocationReason(Enum):
    OPERATOR_REVOKED = "operator_revoked"
    PX4_FAILSAFE = "px4_failsafe"
    FAILSAFE_STATE_UNKNOWN = "failsafe_state_unknown"
    TELEMETRY_LINK_LOST = "telemetry_link_lost"
    PILOT_TAKEOVER = "pilot_takeover"
    PX4_RECOVERY_MODE = "px4_recovery_mode"
    FLIGHT_ENDED = "flight_ended"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class DelegationConfig:
    """Timing limits. MODEL INPUTS / PLACEHOLDERS, not derived from testing."""

    max_telemetry_age_s: float = 1.0
    max_grant_age_s: float = 2.0

    def validate(self) -> None:
        for name in ("max_telemetry_age_s", "max_grant_age_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class GrantCommand:
    """Ground-station delegation command as received by the companion."""

    sequence: int
    issued_at_s: float  # on the companion's monotonic clock


@dataclass(frozen=True)
class GrantResult:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class RevocationAlert:
    """Notification owed to the ground station (R6)."""

    reason: RevocationReason
    detail: str
    at_s: float


class DelegationAuthority:
    """Tracks whether the operator has currently delegated mission actions."""

    def __init__(self, config: DelegationConfig | None = None) -> None:
        self._config = config or DelegationConfig()
        self._config.validate()
        self._delegated = False
        self._highest_sequence: int | None = None
        self._last_obs_s: float | None = None
        self._last_snapshot: VehicleSnapshot | None = None
        self._last_failsafe: bool | None = None
        self._alerts: list[RevocationAlert] = []
        self._flew_under_grant = False

    # ------------------------------------------------------------------ state
    def delegated(self, now_s: float) -> bool:
        """Current authority. Revokes first if observations have gone stale."""

        self._check_observation_freshness(now_s)
        return self._delegated

    def apply_to(self, snapshot: VehicleSnapshot, now_s: float) -> VehicleSnapshot:
        """Return ``snapshot`` with ``operator_delegated`` set from this authority."""

        return replace(snapshot, operator_delegated=self.delegated(now_s))

    def drain_alerts(self) -> tuple[RevocationAlert, ...]:
        alerts, self._alerts = tuple(self._alerts), []
        return alerts

    # ------------------------------------------------------------- telemetry
    def observe(
        self, snapshot: VehicleSnapshot, failsafe_active: bool | None, now_s: float
    ) -> None:
        """Record the latest PX4 state and revoke if any R6 condition holds."""

        if not math.isfinite(now_s) or (self._last_obs_s is not None and now_s < self._last_obs_s):
            self._revoke(RevocationReason.INVALID_INPUT, "clock invalid or went backwards", now_s)
            return
        previous = self._last_snapshot
        self._last_obs_s = now_s
        self._last_snapshot = snapshot
        self._last_failsafe = failsafe_active
        problem = self._unhealthy(snapshot, failsafe_active)
        if problem is None and self._delegated:
            problem = self._flight_ended(previous, snapshot)
        if problem is not None:
            self._revoke(*problem, now_s)
            return
        if self._delegated and snapshot.in_air:
            self._flew_under_grant = True

    # -------------------------------------------------------------- commands
    def request_grant(self, command: GrantCommand, now_s: float) -> GrantResult:
        """Handle a ground-station grant. Never restores authority implicitly."""

        seq = command.sequence
        if isinstance(seq, bool) or not isinstance(seq, int):
            return GrantResult(False, "grant sequence must be an integer")
        if self._highest_sequence is not None and seq <= self._highest_sequence:
            return GrantResult(False, f"grant sequence {seq} is not new; re-send a fresh command")
        # Record every new sequence, accepted or not, so it cannot be replayed.
        self._highest_sequence = seq

        if not (math.isfinite(now_s) and math.isfinite(command.issued_at_s)):
            return GrantResult(False, "grant or clock time is not finite")
        age = now_s - command.issued_at_s
        if age < 0.0 or age > self._config.max_grant_age_s:
            return GrantResult(False, f"grant age {age:.2f} s outside allowed window")

        self._check_observation_freshness(now_s)
        if self._last_snapshot is None or self._last_obs_s is None:
            return GrantResult(False, "no vehicle observation yet")
        if now_s - self._last_obs_s > self._config.max_telemetry_age_s:
            return GrantResult(False, "vehicle observation is stale")
        problem = self._unhealthy(self._last_snapshot, self._last_failsafe)
        if problem is not None:
            return GrantResult(False, f"vehicle not eligible: {problem[1]}")
        if self._delegated:
            return GrantResult(True, "already delegated")
        self._delegated = True
        self._flew_under_grant = bool(self._last_snapshot.in_air)
        return GrantResult(True, "delegation granted")

    def revoke_by_operator(self, now_s: float) -> None:
        self._revoke(RevocationReason.OPERATOR_REVOKED, "ground station revoked delegation", now_s)

    # -------------------------------------------------------------- internals
    def _unhealthy(
        self, snapshot: VehicleSnapshot, failsafe_active: bool | None
    ) -> tuple[RevocationReason, str] | None:
        age = snapshot.telemetry_age_s
        if not math.isfinite(age) or age < 0.0:
            return RevocationReason.INVALID_INPUT, "telemetry age invalid"
        if age > self._config.max_telemetry_age_s:
            return RevocationReason.TELEMETRY_LINK_LOST, f"telemetry age {age:.2f} s"
        if failsafe_active is None:
            return RevocationReason.FAILSAFE_STATE_UNKNOWN, "PX4 failsafe state unknown"
        if failsafe_active:
            return RevocationReason.PX4_FAILSAFE, "PX4 failsafe active"
        mode = snapshot.flight_mode.strip().upper()
        if mode in PILOT_CONTROLLED_MODES:
            return RevocationReason.PILOT_TAKEOVER, f"pilot mode {mode}"
        if mode in AUTOPILOT_RECOVERY_MODES:
            return RevocationReason.PX4_RECOVERY_MODE, f"PX4 mode {mode}"
        if snapshot.in_air and not snapshot.armed:
            return RevocationReason.INVALID_INPUT, "in_air reported while disarmed"
        return None

    def _flight_ended(
        self, previous: VehicleSnapshot | None, snapshot: VehicleSnapshot
    ) -> tuple[RevocationReason, str] | None:
        if previous is not None and previous.armed and not snapshot.armed:
            return RevocationReason.FLIGHT_ENDED, "vehicle disarmed"
        if self._flew_under_grant and not snapshot.in_air:
            return RevocationReason.FLIGHT_ENDED, "vehicle landed"
        return None

    def _check_observation_freshness(self, now_s: float) -> None:
        if not self._delegated:
            return
        if not math.isfinite(now_s) or self._last_obs_s is None or now_s < self._last_obs_s:
            self._revoke(RevocationReason.INVALID_INPUT, "clock invalid or went backwards", now_s)
            return
        gap = now_s - self._last_obs_s
        if gap > self._config.max_telemetry_age_s:
            self._revoke(
                RevocationReason.TELEMETRY_LINK_LOST,
                f"no vehicle observation for {gap:.2f} s",
                now_s,
            )

    def _revoke(self, reason: RevocationReason, detail: str, now_s: float) -> None:
        if not self._delegated:
            return  # alert only on the delegated -> revoked transition
        self._delegated = False
        self._flew_under_grant = False
        self._alerts.append(RevocationAlert(reason, detail, now_s))
