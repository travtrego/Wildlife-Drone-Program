# Coyote ground-station code

Runs on the operator's ground computer, not on the Jetson.

## `grant_sender.py`

Ground-side half of the R6 grant command. Owner decision 2026-11-06: the grant is sent by a small ground-side script/app that increments the grant sequence on every send, so the companion's "new command only" replay rule stays in force; a fixed QGroundControl button is not used because it cannot change the sequence.

- `GrantSequenceStore` keeps the last sequence in a small JSON file and hands out the next one. The new value is written atomically before it is returned, so a crash only skips a number and never reuses one. A missing file starts at 1. A corrupt or out-of-range file raises rather than guessing (a guessed lower number would only be refused by the companion).
- `grant_command_fields` / `revoke_command_fields` / `next_grant_fields` build the `COMMAND_LONG` fields that [`coyote/autonomy/grant_transport.py`](../autonomy/grant_transport.py) decodes. Ids and command number come from the same `GrantTransportConfig` (**model inputs**: MAVLink conventions, not Coyote parameters).
- `interpret_grant_ack` classifies the companion's candidate `COMMAND_ACK` reply as `CONFIRMED`, `REFUSED` or `UNMATCHED`. It matches only a reply from the configured companion (1/191), addressed to this ground station (255/190), for the grant command id, echoing the expected sequence (0 for a revoke); anything else, such as an automatic answer without the echo, is `UNMATCHED` and must not be shown as a confirmation. `CONFIRMED` means accepted when handled, not that delegation is still in force. No reply means unknown, never granted. Not yet used by the SITL sender.

Not written yet, on purpose: opening a MAVLink link and sending. The sender's system/component id must match the companion's configured ground station (default 255/190), and whether PX4 forwards the command to the companion is unobserved. That send step must be SITL/loopback-only first.

Evidence status: **unit-tested only** (`tests/test_coyote_grant_sender.py`; reply decoding in `tests/test_coyote_grant_ack.py`), including a round trip through the companion decoder and `DelegationAuthority` (grant → revoke → re-grant accepted). Nothing has been sent in SITL.
