import math

import pytest

from coyote.autonomy.action_gate import VehicleSnapshot
from coyote.autonomy.delegation import (
    DelegationAuthority,
    GrantCommand,
    RevocationAlert,
    RevocationReason,
)
from coyote.autonomy.ground_alerts import (
    STATUSTEXT_MAX_CHARS,
    AlertSeverity,
    GroundAlertOutbox,
    OutboxConfig,
    StatusMessage,
    format_status_text,
)


def alert(reason: RevocationReason = RevocationReason.TELEMETRY_LINK_LOST, t: float = 0.0):
    return RevocationAlert(reason, "detail kept locally " * 10, t)


class FlakySender:
    """Records lines; fails while ``up`` is False."""

    def __init__(self) -> None:
        self.up = True
        self.sent: list[StatusMessage] = []
        self.attempts = 0

    def __call__(self, message: StatusMessage) -> bool:
        self.attempts += 1
        if not self.up:
            return False
        self.sent.append(message)
        return True


# ------------------------------------------------------------- formatting
@pytest.mark.parametrize("reason", list(RevocationReason))
def test_every_reason_formats_to_short_ascii_statustext(reason: RevocationReason) -> None:
    message = format_status_text(alert(reason))
    assert 0 < len(message.text) <= STATUSTEXT_MAX_CHARS
    assert message.text.isascii()
    assert message.text.startswith("COYOTE AUTONOMY OFF: ")
    assert "detail" not in message.text  # full detail stays in the local record


def test_reasons_get_distinct_labels_so_operator_can_tell_them_apart() -> None:
    texts = {format_status_text(alert(r)).text for r in RevocationReason}
    assert len(texts) == len(RevocationReason)


def test_severity_reflects_who_caused_the_revocation() -> None:
    assert (
        format_status_text(alert(RevocationReason.PX4_FAILSAFE)).severity is AlertSeverity.CRITICAL
    )
    assert format_status_text(alert(RevocationReason.FLIGHT_ENDED)).severity is AlertSeverity.INFO
    operator = format_status_text(alert(RevocationReason.OPERATOR_REVOKED))
    assert operator.severity is AlertSeverity.NOTICE
    for reason in (
        RevocationReason.TELEMETRY_LINK_LOST,
        RevocationReason.PILOT_TAKEOVER,
        RevocationReason.PX4_RECOVERY_MODE,
        RevocationReason.FAILSAFE_STATE_UNKNOWN,
        RevocationReason.INVALID_INPUT,
    ):
        assert format_status_text(alert(reason)).severity is AlertSeverity.WARNING


def test_severity_names_match_mavsdk_status_text_type_members() -> None:
    # mavsdk.server_utility.StatusTextType members in MAVSDK-Python 3.17.2.
    mavsdk_names = {"DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"}
    assert {s.name for s in AlertSeverity} <= mavsdk_names


# ------------------------------------------------------------- delivery
def test_failed_send_keeps_alert_and_retries_after_interval() -> None:
    outbox = GroundAlertOutbox(OutboxConfig(retry_interval_s=0.5))
    outbox.enqueue([alert()])
    sender = FlakySender()
    sender.up = False

    assert outbox.deliver(sender, 10.0) == 0
    assert len(outbox.pending()) == 1
    assert outbox.deliver(sender, 10.2) == 0  # inside retry interval: no attempt
    assert sender.attempts == 1

    sender.up = True
    assert outbox.deliver(sender, 10.5) == 1
    assert outbox.pending() == ()
    assert [m.text for m in sender.sent] == ["COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST"]


def test_sender_exception_counts_as_failure_not_crash() -> None:
    outbox = GroundAlertOutbox()
    outbox.enqueue([alert()])

    def broken(_: StatusMessage) -> bool:
        raise ConnectionError("link down")

    assert outbox.deliver(broken, 1.0) == 0
    assert len(outbox.pending()) == 1


def test_non_true_return_is_a_failure() -> None:
    outbox = GroundAlertOutbox()
    outbox.enqueue([alert()])
    assert outbox.deliver(lambda _: None, 1.0) == 0  # type: ignore[arg-type,return-value]
    assert len(outbox.pending()) == 1


def test_alerts_delivered_in_revocation_order_without_skipping() -> None:
    outbox = GroundAlertOutbox()
    reasons = [
        RevocationReason.PILOT_TAKEOVER,
        RevocationReason.PX4_FAILSAFE,
        RevocationReason.FLIGHT_ENDED,
    ]
    outbox.enqueue(alert(r, i) for i, r in enumerate(reasons))
    sent: list[str] = []

    def fail_second_attempt(message: StatusMessage) -> bool:
        sent.append(message.text)
        return len(sent) != 2

    assert outbox.deliver(fail_second_attempt, 0.0) == 1
    assert outbox.deliver(fail_second_attempt, 5.0) == 2
    # Second line was attempted, failed, then re-sent before the third.
    assert sent == [
        "COYOTE AUTONOMY OFF: PILOT TAKEOVER",
        "COYOTE AUTONOMY OFF: PX4 FAILSAFE",
        "COYOTE AUTONOMY OFF: PX4 FAILSAFE",
        "COYOTE AUTONOMY OFF: FLIGHT ENDED",
    ]
    assert outbox.delivered_count == 3


def test_async_style_api_repeats_in_flight_message_until_resolved() -> None:
    outbox = GroundAlertOutbox()
    outbox.enqueue([alert(RevocationReason.PILOT_TAKEOVER), alert(RevocationReason.FLIGHT_ENDED)])
    first = outbox.next_message(0.0)
    assert outbox.next_message(0.1) == first  # not advanced until marked
    outbox.mark_sent()
    assert outbox.next_message(0.1).text.endswith("FLIGHT ENDED")


def test_mark_without_in_flight_message_is_an_error() -> None:
    outbox = GroundAlertOutbox()
    with pytest.raises(RuntimeError):
        outbox.mark_sent()
    with pytest.raises(RuntimeError):
        outbox.mark_failed(0.0)


def test_empty_outbox_has_nothing_to_send() -> None:
    assert GroundAlertOutbox().next_message(0.0) is None


# ------------------------------------------------------------- overflow
def test_overflow_drops_oldest_and_reports_drop_count_first() -> None:
    outbox = GroundAlertOutbox(OutboxConfig(max_pending=2))
    outbox.enqueue(
        [
            alert(RevocationReason.PILOT_TAKEOVER, 1),
            alert(RevocationReason.PX4_FAILSAFE, 2),
            alert(RevocationReason.FLIGHT_ENDED, 3),
        ]
    )
    assert [a.at_s for a in outbox.pending()] == [2, 3]
    sender = FlakySender()
    outbox.deliver(sender, 0.0)
    assert [m.text for m in sender.sent] == [
        "COYOTE: 1 AUTONOMY ALERTS DROPPED",
        "COYOTE AUTONOMY OFF: PX4 FAILSAFE",
        "COYOTE AUTONOMY OFF: FLIGHT ENDED",
    ]
    assert outbox.dropped_total == 1 and outbox.dropped_unreported == 0


def test_overflow_never_drops_the_alert_being_sent() -> None:
    outbox = GroundAlertOutbox(OutboxConfig(max_pending=2))
    outbox.enqueue(
        [alert(RevocationReason.PILOT_TAKEOVER, 1), alert(RevocationReason.PX4_FAILSAFE, 2)]
    )
    in_flight = outbox.next_message(0.0)
    outbox.enqueue([alert(RevocationReason.FLIGHT_ENDED, 3)])
    outbox.mark_sent()
    assert in_flight.text.endswith("PILOT TAKEOVER")
    assert [a.at_s for a in outbox.pending()] == [3]
    assert outbox.dropped_unreported == 1


def test_drops_during_in_flight_drop_notice_are_still_reported() -> None:
    outbox = GroundAlertOutbox(OutboxConfig(max_pending=2))
    outbox.enqueue(alert(t=i) for i in range(3))  # one dropped
    notice = outbox.next_message(0.0)
    assert notice.text == "COYOTE: 1 AUTONOMY ALERTS DROPPED"
    outbox.enqueue([alert(t=10)])  # another drop while the notice is in flight
    outbox.mark_sent()
    assert outbox.dropped_unreported == 1
    assert outbox.next_message(0.0).text == "COYOTE: 1 AUTONOMY ALERTS DROPPED"


# ------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "config",
    [
        OutboxConfig(max_pending=1),
        OutboxConfig(max_pending=0),
        OutboxConfig(max_pending=True),
        OutboxConfig(retry_interval_s=0.0),
        OutboxConfig(retry_interval_s=math.nan),
        OutboxConfig(retry_interval_s=math.inf),
    ],
)
def test_bad_config_rejected(config: OutboxConfig) -> None:
    with pytest.raises(ValueError):
        GroundAlertOutbox(config)


@pytest.mark.parametrize("bad", [math.nan, math.inf, True, "1"])
def test_bad_time_rejected(bad: object) -> None:
    outbox = GroundAlertOutbox()
    with pytest.raises(ValueError):
        outbox.next_message(bad)  # type: ignore[arg-type]


def test_only_revocation_alerts_accepted() -> None:
    with pytest.raises(TypeError):
        GroundAlertOutbox().enqueue(["not an alert"])  # type: ignore[list-item]


# ------------------------------------------------------- with delegation
def snap(**overrides: object) -> VehicleSnapshot:
    values: dict[str, object] = dict(
        flight_mode="HOLD",
        armed=True,
        in_air=True,
        relative_altitude_m=10.0,
        battery_remaining_fraction=0.9,
        telemetry_age_s=0.1,
    )
    values.update(overrides)
    return VehicleSnapshot(**values)  # type: ignore[arg-type]


def test_link_loss_alert_survives_outage_and_reaches_ground_station_later() -> None:
    authority = DelegationAuthority()
    outbox = GroundAlertOutbox()
    sender = FlakySender()
    authority.observe(snap(), False, 0.0)
    assert authority.request_grant(GrantCommand(1, 0.0), 0.0).accepted

    # Telemetry goes silent; the link to the ground station is down too.
    sender.up = False
    assert not authority.delegated(3.0)
    outbox.collect(authority)
    assert authority.drain_alerts() == ()  # authority's queue is now empty
    outbox.deliver(sender, 3.0)
    assert sender.sent == []
    assert [a.reason for a in outbox.pending()] == [RevocationReason.TELEMETRY_LINK_LOST]

    sender.up = True
    outbox.deliver(sender, 4.0)
    assert [(m.severity, m.text) for m in sender.sent] == [
        (AlertSeverity.WARNING, "COYOTE AUTONOMY OFF: PX4 TELEMETRY LOST")
    ]
    assert not authority.delegated(4.0)  # delivery never restores authority
