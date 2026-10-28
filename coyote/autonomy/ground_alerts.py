"""Hold R6 revocation alerts until the ground station has actually received them.

R6 (coyote/DECISIONS.md, owner decision 2026-10-18) requires the ground
station to notify the operator, with the reason, whenever companion authority
is revoked. :class:`~coyote.autonomy.delegation.DelegationAuthority` queues one
:class:`~coyote.autonomy.delegation.RevocationAlert` per revocation, but
``drain_alerts()`` empties that queue. Revocations happen most often exactly
when links are failing, so an adapter that drains and then fails to send would
silently lose the alert. This module is the missing step between the two:

* :class:`GroundAlertOutbox` takes drained alerts and keeps each one until the
  sender reports success. A failed send leaves it at the head of the queue, so
  alerts arrive in revocation order and none is skipped.
* :func:`format_status_text` turns an alert into a short ASCII line with a
  severity, sized for a MAVLink ``STATUSTEXT`` message (50 characters), which
  is what MAVSDK ``server_utility.send_status_text`` sends and ground stations
  display. The full ``detail`` string stays in the local record only.

Implementation choices (not new owner requirements)
---------------------------------------------------
* **Transport is injected.** The outbox does not import MAVSDK. A caller asks
  :meth:`GroundAlertOutbox.next_message` for the next line, sends it however
  it likes (sync or async) and reports :meth:`mark_sent` or
  :meth:`mark_failed`. Severity names match ``mavsdk.server_utility.
  StatusTextType`` member names so an adapter can map by name. Whether a
  companion-originated STATUSTEXT is shown by the operator's ground station is
  **not yet observed** in SITL.
* **Bounded, never silent.** The queue holds at most ``max_pending`` alerts
  (model input). On overflow the oldest is dropped, counted, and a "N alerts
  dropped" line is sent before the remaining alerts, so loss is visible.
* **Retry spacing.** After a failed send, :meth:`next_message` returns
  ``None`` until ``retry_interval_s`` has passed, so a dead link is not
  hammered. A successful send allows the next line immediately.
* **Acknowledgement means sent, not read.** ``mark_sent`` records that the
  transport accepted the message. Confirming that the operator saw it needs a
  ground-station acknowledgement, which this module does not define.

Nothing here commands the vehicle or changes delegation state. Defaults are
MODEL INPUTS / development placeholders, not tested values.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

from coyote.autonomy.delegation import DelegationAuthority, RevocationAlert, RevocationReason

# MAVLink STATUSTEXT carries at most 50 characters of text per message.
STATUSTEXT_MAX_CHARS = 50
TEXT_PREFIX = "COYOTE AUTONOMY OFF: "


class AlertSeverity(Enum):
    """Subset of MAVLink severities; names match MAVSDK ``StatusTextType``."""

    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# Short operator-facing label and severity per reason. A routine end of flight
# or an operator's own revoke is informational; anything the operator did not
# ask for is at least a warning, and a PX4 failsafe is critical.
_REASON_TEXT: dict[RevocationReason, tuple[str, AlertSeverity]] = {
    RevocationReason.OPERATOR_REVOKED: ("OPERATOR REVOKE", AlertSeverity.NOTICE),
    RevocationReason.FLIGHT_ENDED: ("FLIGHT ENDED", AlertSeverity.INFO),
    RevocationReason.PX4_FAILSAFE: ("PX4 FAILSAFE", AlertSeverity.CRITICAL),
    RevocationReason.FAILSAFE_STATE_UNKNOWN: ("FAILSAFE STATE UNKNOWN", AlertSeverity.WARNING),
    RevocationReason.TELEMETRY_LINK_LOST: ("PX4 TELEMETRY LOST", AlertSeverity.WARNING),
    RevocationReason.PILOT_TAKEOVER: ("PILOT TAKEOVER", AlertSeverity.WARNING),
    RevocationReason.PX4_RECOVERY_MODE: ("PX4 RTL/LAND", AlertSeverity.WARNING),
    RevocationReason.INVALID_INPUT: ("INVALID STATE", AlertSeverity.WARNING),
}


@dataclass(frozen=True)
class OutboxConfig:
    """MODEL INPUTS / PLACEHOLDERS: not derived from SITL or flight testing."""

    max_pending: int = 16
    retry_interval_s: float = 0.5

    def validate(self) -> None:
        if isinstance(self.max_pending, bool) or not isinstance(self.max_pending, int):
            raise ValueError("max_pending must be an integer")
        if self.max_pending < 2:
            # One slot for the alert being sent plus at least one for new ones.
            raise ValueError("max_pending must be at least 2")
        if not math.isfinite(self.retry_interval_s) or self.retry_interval_s <= 0.0:
            raise ValueError("retry_interval_s must be a positive finite number")


@dataclass(frozen=True)
class StatusMessage:
    """One line for the ground station."""

    severity: AlertSeverity
    text: str


def format_status_text(alert: RevocationAlert) -> StatusMessage:
    """Return the ground-station line for ``alert``: fixed prefix + short reason.

    The result is ASCII and at most :data:`STATUSTEXT_MAX_CHARS` characters.
    An unexpected reason falls back to its enum value at WARNING severity.
    """

    fallback = (str(getattr(alert.reason, "value", alert.reason)).upper(), AlertSeverity.WARNING)
    label, severity = _REASON_TEXT.get(alert.reason, fallback)
    return StatusMessage(severity, _fit(TEXT_PREFIX + label))


def _dropped_message(count: int) -> StatusMessage:
    return StatusMessage(AlertSeverity.WARNING, _fit(f"COYOTE: {count} AUTONOMY ALERTS DROPPED"))


def _fit(text: str) -> str:
    ascii_text = text.encode("ascii", "replace").decode("ascii")
    return ascii_text[:STATUSTEXT_MAX_CHARS]


class GroundAlertOutbox:
    """Ordered, bounded store of revocation alerts awaiting delivery."""

    def __init__(self, config: OutboxConfig | None = None) -> None:
        self._config = config or OutboxConfig()
        self._config.validate()
        self._pending: deque[RevocationAlert] = deque()
        self._dropped_unreported = 0
        self._retry_after_s: float | None = None
        self._in_flight: StatusMessage | None = None
        # Drop count carried by an in-flight drop notice; None if the in-flight
        # line is the head alert.
        self._in_flight_drop_count: int | None = None
        self.delivered_count = 0
        self.dropped_total = 0

    # ------------------------------------------------------------- intake
    def enqueue(self, alerts: Iterable[RevocationAlert]) -> None:
        for alert in alerts:
            if not isinstance(alert, RevocationAlert):
                raise TypeError("outbox accepts RevocationAlert objects only")
            if len(self._pending) >= self._config.max_pending:
                if self._head_alert_in_flight():
                    # Never drop the alert a sender is currently transmitting.
                    del self._pending[1]
                else:
                    self._pending.popleft()
                self._dropped_unreported += 1
                self.dropped_total += 1
            self._pending.append(alert)

    def collect(self, authority: DelegationAuthority) -> None:
        """Move every queued alert out of ``authority`` into this outbox."""

        self.enqueue(authority.drain_alerts())

    # ------------------------------------------------------------- delivery
    def pending(self) -> tuple[RevocationAlert, ...]:
        """Alerts not yet confirmed sent, oldest first (full detail retained)."""

        return tuple(self._pending)

    @property
    def dropped_unreported(self) -> int:
        return self._dropped_unreported

    def next_message(self, now_s: float) -> StatusMessage | None:
        """The line to send now, or ``None`` if nothing is due.

        Returns the same line again until :meth:`mark_sent` or
        :meth:`mark_failed` is called for it. A drop notice goes first.
        """

        _require_finite_time(now_s)
        if self._in_flight is not None:
            return self._in_flight
        if self._retry_after_s is not None and now_s < self._retry_after_s:
            return None
        if self._dropped_unreported:
            self._in_flight = _dropped_message(self._dropped_unreported)
            self._in_flight_drop_count = self._dropped_unreported
        elif self._pending:
            self._in_flight = format_status_text(self._pending[0])
            self._in_flight_drop_count = None
        return self._in_flight

    def mark_sent(self) -> None:
        """The transport accepted the line returned by :meth:`next_message`."""

        if self._in_flight is None:
            raise RuntimeError("mark_sent called with no message in flight")
        if self._in_flight_drop_count is None:
            self._pending.popleft()
            self.delivered_count += 1
        else:
            # Drops that happened while the notice was in flight stay unreported.
            self._dropped_unreported -= self._in_flight_drop_count
        self._clear_in_flight()
        self._retry_after_s = None

    def mark_failed(self, now_s: float) -> None:
        """The send failed; keep the message and wait before retrying."""

        _require_finite_time(now_s)
        if self._in_flight is None:
            raise RuntimeError("mark_failed called with no message in flight")
        self._clear_in_flight()
        self._retry_after_s = now_s + self._config.retry_interval_s

    def deliver(self, send: Callable[[StatusMessage], bool], now_s: float) -> int:
        """Send due lines through a synchronous ``send``; return how many sent.

        ``send`` returns True on success. False or any exception counts as a
        failure; delivery then stops until the retry interval has passed.
        """

        sent = 0
        while (message := self.next_message(now_s)) is not None:
            try:
                ok = send(message) is True
            except Exception:  # noqa: BLE001 - any transport error is a failed send
                ok = False
            if not ok:
                self.mark_failed(now_s)
                break
            self.mark_sent()
            sent += 1
        return sent

    # ------------------------------------------------------------ internals
    def _head_alert_in_flight(self) -> bool:
        return self._in_flight is not None and self._in_flight_drop_count is None

    def _clear_in_flight(self) -> None:
        self._in_flight = None
        self._in_flight_drop_count = None


def _require_finite_time(now_s: float) -> None:
    if isinstance(now_s, bool) or not isinstance(now_s, int | float) or not math.isfinite(now_s):
        raise ValueError("outbox time must be a finite monotonic time")
