"""Machine-readable record of one SITL ``waypoint_mission_flight`` run.

Simulation tooling only. It never talks to a vehicle: it turns what the flight
script already knows (code revision, configuration, mission file, companion
settings in use, PX4 limit parameters it read, monitor and return-watch
results, trace lines) into one small JSON file, so a laptop SITL session can be
sent back and turned into a dated evidence record without copying terminal
output by hand.

A record is a description of one run, not evidence by itself that the run was
simulated or that anything passed: the outcome is the script's own verdict.
It deliberately does not capture what the script cannot see (listed in
``NOT_CAPTURED``): the PX4/Gazebo versions, the ULog and its checksum, the PX4
console and the ground station. Those still have to be recorded by hand, as in
the SITL session checklist.

Records are summaries, not raw logs, but they stay outside Git by default
(``sitl_runs/`` is ignored); the owner decides what goes into ``docs/``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from x500.flight.preflight import PreflightRefused
from x500.flight.px4_limits import Px4LimitsRefused
from x500.flight.waypoint_mission import MissionCheckError

SCHEMA = "x500-sitl-flight-record/1"

# What a run record cannot contain; the checklist asks for these by hand.
NOT_CAPTURED = (
    "PX4-Autopilot revision and build target",
    "Gazebo version",
    "ULog file name and sha256",
    "PX4 console lines around each event",
    "whether QGroundControl or another ground station was connected",
)

_LABEL = re.compile(r"[A-Za-z0-9_-]{1,32}")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Outcome(Enum):
    PASS = "pass"
    FAIL = "fail"
    INJECTED_FAULT_PATH_OK = "injected_fault_path_ok"
    INJECTED_FAULT_PATH_FAIL = "injected_fault_path_fail"
    REFUSED_MISSION_CHECK = "refused_mission_check"
    REFUSED_PREFLIGHT = "refused_preflight"
    REFUSED_PX4_LIMITS = "refused_px4_limits"
    INTERRUPTED = "interrupted"
    ERROR = "error"


def validate_label(label: str) -> str:
    """A run label (e.g. a checklist row ``A3``) safe to put in a file name."""

    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ValueError("Run label must be 1-32 characters of letters, digits, '-' or '_'")
    return label


def prepare_record_dir(path: str | Path) -> Path:
    """Create the record directory if needed; refuse a path that is not a directory."""

    directory = Path(path).expanduser()
    if directory.exists() and not directory.is_dir():
        raise ValueError(f"Record directory {str(directory)!r} exists and is not a directory")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def code_revision(
    repo_root: Path = _REPO_ROOT,
    run: Callable[..., Any] = subprocess.run,
) -> dict[str, object]:
    """Best-effort git commit and whether tracked files differ from it.

    Never raises: a missing git or a non-checkout is recorded as an error text.
    """

    def git(*args: str) -> str:
        done = run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return done.stdout.strip()

    try:
        commit = git("rev-parse", "HEAD")
        changed = git("status", "--porcelain", "--untracked-files=no")
    except Exception as exc:  # FileNotFoundError, CalledProcessError, timeout
        return {"commit": None, "tracked_changes": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"commit": commit, "tracked_changes": bool(changed), "error": None}


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify(result: Any | None, injecting: bool, error: BaseException | None) -> Outcome:
    """The script's verdict for this run, using the same rules as its exit message."""

    if error is not None:
        if isinstance(error, MissionCheckError):
            return Outcome.REFUSED_MISSION_CHECK
        if isinstance(error, PreflightRefused):
            return Outcome.REFUSED_PREFLIGHT
        if isinstance(error, Px4LimitsRefused):
            return Outcome.REFUSED_PX4_LIMITS
        if isinstance(error, KeyboardInterrupt):
            return Outcome.INTERRUPTED
        return Outcome.ERROR
    if result is None:
        return Outcome.ERROR
    if injecting:
        if result.injected_fault_path_ok:
            return Outcome.INJECTED_FAULT_PATH_OK
        return Outcome.INJECTED_FAULT_PATH_FAIL
    return Outcome.PASS if result.passed else Outcome.FAIL


def _jsonable(value: Any) -> Any:
    """Plain JSON values; non-finite floats become strings (JSON has no NaN)."""

    if isinstance(value, Enum):
        return _jsonable(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _error_entry(error: BaseException | None) -> dict[str, object] | None:
    if error is None:
        return None
    entry: dict[str, object] = {"type": type(error).__name__, "message": str(error)}
    reasons = getattr(error, "reasons", None)
    if reasons:
        entry["reasons"] = list(reasons)
    return entry


def build_record(
    *,
    started_utc: datetime,
    ended_utc: datetime,
    label: str | None,
    argv: Sequence[str],
    revision: dict[str, object],
    config: Any,
    mission_path: Path,
    mission_sha256: str,
    waypoints: Sequence[Any],
    mission_limits: Any,
    preflight_limits: Any,
    monitor_settings: Any,
    return_settings: Any,
    injecting: bool,
    result: Any | None,
    error: BaseException | None,
    lines: Sequence[str],
) -> dict[str, Any]:
    """Assemble one run record. Pure: no clock, file or vehicle access."""

    outcome = classify(result, injecting, error)
    px4_values: dict[str, object] = {}
    if result is not None:
        px4_values = dict(result.px4_limit_values)
    elif isinstance(error, Px4LimitsRefused):
        px4_values = dict(error.values)
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "PX4 SITL run of simulation.mavsdk.waypoint_mission_flight",
        "label": label,
        "started_utc": started_utc.isoformat(),
        "ended_utc": ended_utc.isoformat(),
        "duration_s": round((ended_utc - started_utc).total_seconds(), 3),
        "argv": list(argv),
        "code": revision,
        "outcome": outcome.value,
        "sitl_fault_injection": injecting,
        "error": _error_entry(error),
        "config": config,
        "mission": {"path": mission_path, "sha256": mission_sha256, "waypoints": waypoints},
        # Model inputs / SITL placeholders actually in use for this run.
        "companion_settings": {
            "mission_limits": mission_limits,
            "preflight_limits": preflight_limits,
            "monitor": monitor_settings,
            "return_watch": return_settings,
        },
        # Read-only PX4 parameter values from the limit check (or read errors);
        # empty when the run ended before the check.
        "px4_limit_params_read": px4_values,
        "monitor_status": result.status if result is not None else None,
        "rtl_requested": result.rtl_requested if result is not None else None,
        "follow_up_reason": result.follow_up_reason if result is not None else None,
        "return_status": result.return_status if result is not None else None,
        "stream_errors": result.stream_errors if result is not None else {},
        "lines": list(lines),
        "not_captured": list(NOT_CAPTURED),
    }
    return _jsonable(record)


def write_record(record: dict[str, Any], directory: Path) -> Path:
    """Write the record as a new file; never overwrites an existing one."""

    stamp = record["started_utc"][:19].replace("-", "").replace(":", "")
    stem = f"x500-flight-{stamp}Z-{record.get('label') or 'run'}-{record['outcome']}"
    text = json.dumps(record, indent=2, allow_nan=False) + "\n"
    for attempt in range(1, 100):
        name = f"{stem}.json" if attempt == 1 else f"{stem}-{attempt}.json"
        path = directory / name
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            continue
        return path
    raise FileExistsError(f"Too many run records named {stem}* in {directory}")


def utc_now() -> datetime:
    return datetime.now(UTC)
