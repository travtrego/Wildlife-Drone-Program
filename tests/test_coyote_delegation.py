import math
from dataclasses import replace

import pytest

from coyote.autonomy.action_gate import ActionKind, ActionRequest, VehicleSnapshot, evaluate_request
from coyote.autonomy.delegation import (
    DelegationAuthority,
    DelegationConfig,
    GrantCommand,
    RevocationReason,
)

FLYING = VehicleSnapshot(
    flight_mode="HOLD",
    armed=True,
    in_air=True,
    relative_altitude_m=20.0,
    battery_remaining_fraction=0.8,
    telemetry_age_s=0.1,
)
HOLD = ActionRequest(ActionKind.HOLD)
ON_GROUND = VehicleSnapshot(
    flight_mode="HOLD",
    armed=False,
    in_air=False,
    relative_altitude_m=0.0,
    battery_remaining_fraction=1.0,
    telemetry_age_s=0.1,
)


def delegated_authority(t: float = 10.0, seq: int = 1) -> DelegationAuthority:
    auth = DelegationAuthority()
    auth.observe(FLYING, failsafe_active=False, now_s=t)
    assert auth.request_grant(GrantCommand(seq, t), t).accepted
    assert auth.delegated(t)
    return auth


def test_starts_revoked_and_gate_rejects() -> None:
    auth = DelegationAuthority()
    auth.observe(FLYING, False, 0.0)
    assert not auth.delegated(0.0)
    assert not evaluate_request(HOLD, auth.apply_to(FLYING, 0.0)).allowed
    assert auth.drain_alerts() == ()


def test_grant_enables_gate() -> None:
    auth = delegated_authority()
    assert evaluate_request(HOLD, auth.apply_to(FLYING, 10.1)).allowed


@pytest.mark.parametrize(
    ("snapshot", "failsafe", "reason"),
    [
        (FLYING, True, RevocationReason.PX4_FAILSAFE),
        (FLYING, None, RevocationReason.FAILSAFE_STATE_UNKNOWN),
        (replace(FLYING, telemetry_age_s=1.5), False, RevocationReason.TELEMETRY_LINK_LOST),
        (replace(FLYING, telemetry_age_s=math.nan), False, RevocationReason.INVALID_INPUT),
        (replace(FLYING, flight_mode="POSCTL"), False, RevocationReason.PILOT_TAKEOVER),
        (replace(FLYING, flight_mode="manual"), False, RevocationReason.PILOT_TAKEOVER),
        (
            replace(FLYING, flight_mode="RETURN_TO_LAUNCH"),
            False,
            RevocationReason.PX4_RECOVERY_MODE,
        ),
        (replace(FLYING, flight_mode="LAND"), False, RevocationReason.PX4_RECOVERY_MODE),
        (replace(FLYING, in_air=False), False, RevocationReason.FLIGHT_ENDED),
        (replace(FLYING, armed=False, in_air=False), False, RevocationReason.FLIGHT_ENDED),
        (replace(FLYING, armed=False), False, RevocationReason.INVALID_INPUT),
    ],
)
def test_each_revocation_path_revokes_and_alerts_once(snapshot, failsafe, reason) -> None:
    auth = delegated_authority()
    auth.observe(snapshot, failsafe, 10.2)
    auth.observe(snapshot, failsafe, 10.3)  # persisting condition: no second alert
    assert not auth.delegated(10.3)
    alerts = auth.drain_alerts()
    assert [a.reason for a in alerts] == [reason]
    assert alerts[0].at_s == 10.2
    assert auth.drain_alerts() == ()


def test_revocation_is_sticky_after_condition_clears() -> None:
    auth = delegated_authority()
    auth.observe(replace(FLYING, flight_mode="POSCTL"), False, 10.2)
    auth.observe(FLYING, False, 10.3)  # pilot hands back to HOLD
    assert not auth.delegated(10.3)
    assert not evaluate_request(HOLD, auth.apply_to(FLYING, 10.3)).allowed


def test_missing_observations_revoke_as_link_loss() -> None:
    auth = delegated_authority(t=10.0)
    assert auth.delegated(11.0)  # boundary is inclusive
    assert not auth.delegated(11.01)
    (alert,) = auth.drain_alerts()
    assert alert.reason is RevocationReason.TELEMETRY_LINK_LOST


@pytest.mark.parametrize("now", [9.0, math.nan, math.inf])
def test_invalid_or_backwards_clock_revokes(now) -> None:
    auth = delegated_authority(t=10.0)
    auth.observe(FLYING, False, now)
    assert not auth.delegated(10.1)
    assert auth.drain_alerts()[0].reason is RevocationReason.INVALID_INPUT


def test_operator_revoke_alerts() -> None:
    auth = delegated_authority()
    auth.revoke_by_operator(10.5)
    assert not auth.delegated(10.5)
    assert auth.drain_alerts()[0].reason is RevocationReason.OPERATOR_REVOKED


def test_regrant_requires_new_command_after_revocation() -> None:
    auth = delegated_authority(seq=5)
    auth.observe(FLYING, True, 10.2)
    auth.observe(FLYING, False, 10.3)  # failsafe cleared
    # The old command delivered again (e.g. queued over the link) is refused.
    assert not auth.request_grant(GrantCommand(5, 10.3), 10.3).accepted
    assert not auth.request_grant(GrantCommand(4, 10.3), 10.3).accepted
    assert not auth.delegated(10.3)
    assert auth.request_grant(GrantCommand(6, 10.3), 10.3).accepted
    assert auth.delegated(10.3)


def test_refused_new_sequence_cannot_be_replayed_later() -> None:
    auth = DelegationAuthority()
    auth.observe(replace(FLYING, flight_mode="POSCTL"), False, 0.0)
    assert not auth.request_grant(GrantCommand(1, 0.0), 0.0).accepted
    auth.observe(FLYING, False, 0.5)
    assert not auth.request_grant(GrantCommand(1, 0.5), 0.5).accepted


@pytest.mark.parametrize("issued_at", [7.9, 10.5, math.nan])
def test_old_future_or_invalid_grant_time_refused(issued_at) -> None:
    auth = DelegationAuthority()
    auth.observe(FLYING, False, 10.0)
    assert not auth.request_grant(GrantCommand(1, issued_at), 10.0).accepted
    assert not auth.delegated(10.0)


@pytest.mark.parametrize(
    ("snapshot", "failsafe"),
    [
        (FLYING, True),
        (FLYING, None),
        (replace(FLYING, flight_mode="ALTCTL"), False),
        (replace(FLYING, flight_mode="RETURN_TO_LAUNCH"), False),
        (replace(FLYING, telemetry_age_s=2.0), False),
        (replace(ON_GROUND, flight_mode="POSCTL"), False),
        (replace(FLYING, armed=False), False),
    ],
)
def test_grant_refused_when_vehicle_not_eligible(snapshot, failsafe) -> None:
    auth = DelegationAuthority()
    auth.observe(snapshot, failsafe, 0.0)
    assert not auth.request_grant(GrantCommand(1, 0.0), 0.0).accepted
    assert not auth.delegated(0.0)
    assert auth.drain_alerts() == ()  # nothing was revoked; no alert owed


def test_grant_refused_without_or_with_stale_observation() -> None:
    auth = DelegationAuthority()
    assert not auth.request_grant(GrantCommand(1, 0.0), 0.0).accepted
    auth.observe(FLYING, False, 0.0)
    assert not auth.request_grant(GrantCommand(2, 1.5), 1.5).accepted


@pytest.mark.parametrize("seq", [True, 1.0, "1"])
def test_non_integer_sequence_refused(seq) -> None:
    auth = DelegationAuthority()
    auth.observe(FLYING, False, 0.0)
    assert not auth.request_grant(GrantCommand(seq, 0.0), 0.0).accepted


def test_alerts_queue_until_drained() -> None:
    auth = delegated_authority(seq=1)
    auth.observe(FLYING, True, 10.2)
    auth.observe(FLYING, False, 10.3)
    assert auth.request_grant(GrantCommand(2, 10.3), 10.3).accepted
    auth.observe(replace(FLYING, flight_mode="POSCTL"), False, 10.4)
    reasons = [a.reason for a in auth.drain_alerts()]
    assert reasons == [RevocationReason.PX4_FAILSAFE, RevocationReason.PILOT_TAKEOVER]


@pytest.mark.parametrize(
    "config",
    [
        DelegationConfig(max_telemetry_age_s=0.0),
        DelegationConfig(max_grant_age_s=-1.0),
        DelegationConfig(max_telemetry_age_s=math.inf),
    ],
)
def test_invalid_config_rejected(config) -> None:
    with pytest.raises(ValueError):
        DelegationAuthority(config)


# --- Pre-takeoff grants (owner decision 2026-10-20) -------------------------


def ground_authority(armed: bool = False) -> DelegationAuthority:
    auth = DelegationAuthority()
    auth.observe(replace(ON_GROUND, armed=armed), False, 0.0)
    assert auth.request_grant(GrantCommand(1, 0.0), 0.0).accepted
    return auth


@pytest.mark.parametrize("armed", [False, True])
def test_grant_accepted_on_ground_before_takeoff(armed) -> None:
    auth = ground_authority(armed)
    assert auth.delegated(0.0)
    assert auth.drain_alerts() == ()


def test_ground_grant_does_not_let_gate_allow_requests_on_ground() -> None:
    auth = ground_authority(armed=True)
    snap = auth.apply_to(replace(ON_GROUND, armed=True), 0.0)
    assert snap.operator_delegated
    assert not evaluate_request(HOLD, snap).allowed


def test_ground_grant_carries_through_arming_and_takeoff() -> None:
    auth = ground_authority(armed=False)
    auth.observe(replace(ON_GROUND, armed=True), False, 0.5)
    assert auth.delegated(0.5)
    auth.observe(FLYING, False, 1.0)
    assert auth.delegated(1.0)
    assert evaluate_request(HOLD, auth.apply_to(FLYING, 1.0)).allowed
    assert auth.drain_alerts() == ()


def test_landing_after_flight_ends_the_grant() -> None:
    auth = ground_authority(armed=True)
    auth.observe(FLYING, False, 1.0)
    auth.observe(replace(FLYING, in_air=False), False, 2.0)
    assert not auth.delegated(2.0)
    assert [a.reason for a in auth.drain_alerts()] == [RevocationReason.FLIGHT_ENDED]


def test_disarm_on_ground_after_grant_revokes() -> None:
    auth = ground_authority(armed=True)
    auth.observe(ON_GROUND, False, 0.5)
    assert not auth.delegated(0.5)
    assert [a.reason for a in auth.drain_alerts()] == [RevocationReason.FLIGHT_ENDED]


def test_ground_grant_does_not_carry_into_second_flight() -> None:
    auth = ground_authority(armed=True)
    auth.observe(FLYING, False, 1.0)
    auth.observe(replace(FLYING, in_air=False), False, 2.0)
    auth.observe(FLYING, False, 3.0)  # takes off again without a new grant
    assert not auth.delegated(3.0)


def test_pilot_mode_on_ground_revokes_ground_grant() -> None:
    auth = ground_authority(armed=True)
    auth.observe(replace(ON_GROUND, armed=True, flight_mode="POSCTL"), False, 0.5)
    assert not auth.delegated(0.5)
    assert [a.reason for a in auth.drain_alerts()] == [RevocationReason.PILOT_TAKEOVER]
