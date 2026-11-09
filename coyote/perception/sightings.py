"""Candidate sighting record and human-review rules for the Coyote population database.

Perception plan step 2 ([PERCEPTION_PLAN.md](../PERCEPTION_PLAN.md), stage 6):
every weekly survey should produce labelled data from day one, so the record a
person reviews exists before any detector or re-identification model does.

R4 (owner decisions 2026-10-18 and 2026-11-08): identification is
**human-confirmed**. This module enforces that in the data itself:

* A machine re-identification *suggestion* (:class:`MatchSuggestion`) is stored
  but never sets an identity. :func:`current_outcome` is read only from human
  :class:`ReviewDecision` entries.
* Reviews are an append-only history (who decided what, when). A later review
  supersedes an earlier one; nothing is overwritten.
* :func:`apply_review` refuses (never repairs) a decision that is inconsistent:
  a confirmation without an individual id, an id on a non-confirming outcome,
  "known" for an id not in the database, "new" for an id already in it, a
  decision dated before the sighting or before the previous review, or fewer
  cited marks / images than the :class:`ConfirmationPolicy` requires.
* :func:`confirmed_individuals` checks database integrity: every confirmed
  individual has exactly one founding ("new") sighting.

What this is **not**
--------------------
* Not the database layout or hosting (owner decision pending, PERCEPTION_PLAN
  "Owner decisions needed later"). Records serialise to plain JSON-compatible
  dicts (:func:`sighting_to_record` / :func:`sighting_from_record`) so any store
  can hold them; nothing here writes files or talks to a server.
* Not the confirmation criteria. :class:`ConfirmationPolicy` defaults (at least
  one cited mark and one image) are **development placeholders** until the
  owner decides what counts as a confirmed individual.
* Not evidence that any camera, detector or model can identify individual
  coyotes. Image references point to files kept outside Git (data policy); the
  checksum only lets a later reader detect a changed or swapped file.
* The reviewer field is a name the review tool supplies. Code cannot prove a
  person made the decision; the tool and procedure must.

Runs on the ground computer after flight. Nothing here touches the vehicle.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SightingRecordError(ValueError):
    """A sighting record or review is malformed or inconsistent."""


class ReviewRefused(SightingRecordError):
    """A review decision was refused; the sighting is unchanged."""


class ImageSource(StrEnum):
    """Which permanently installed sensor produced an image (R3)."""

    RGB_STILL = "rgb_still"  # Sony stills camera
    ZOOM_FRAME = "zoom_frame"  # zoom channel of the ZT30-class gimbal
    THERMAL_FRAME = "thermal_frame"  # thermal channel of the ZT30-class gimbal


class PositionSource(StrEnum):
    """Where the sighting position came from. Accuracy is not implied."""

    RTK_FIXED = "rtk_fixed"
    RTK_FLOAT = "rtk_float"
    GNSS = "gnss"
    MANUAL = "manual"  # entered by a person, e.g. from a map


class ReviewOutcome(StrEnum):
    CONFIRMED_KNOWN = "confirmed_known"  # an individual already in the database
    CONFIRMED_NEW = "confirmed_new"  # founds a new individual
    NOT_IDENTIFIABLE = "not_identifiable"  # a coyote, but marks not readable
    NOT_A_COYOTE = "not_a_coyote"


UNREVIEWED = "unreviewed"
CONFIRMING = frozenset({ReviewOutcome.CONFIRMED_KNOWN, ReviewOutcome.CONFIRMED_NEW})


def _utc(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise SightingRecordError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise SightingRecordError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SightingRecordError(f"{name} must be a non-empty string")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SightingRecordError(f"{name} must be a number")
    if not math.isfinite(value):
        raise SightingRecordError(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True)
class ImageRef:
    """A file outside Git, identified by location and SHA-256 checksum."""

    uri: str
    sha256: str
    captured_at: datetime
    source: ImageSource

    def __post_init__(self) -> None:
        _text(self.uri, "image uri")
        if not isinstance(self.sha256, str) or not _SHA256.match(self.sha256):
            raise SightingRecordError("image sha256 must be 64 lowercase hex characters")
        object.__setattr__(self, "captured_at", _utc(self.captured_at, "image captured_at"))
        object.__setattr__(self, "source", ImageSource(self.source))


@dataclass(frozen=True)
class MatchSuggestion:
    """A machine re-ID suggestion. Stored for review and evaluation only."""

    individual_id: str
    score: float  # model-specific scale; never compared across model versions
    model_version: str

    def __post_init__(self) -> None:
        _text(self.individual_id, "suggestion individual_id")
        object.__setattr__(self, "score", _number(self.score, "suggestion score"))
        _text(self.model_version, "suggestion model_version")


@dataclass(frozen=True)
class ReviewDecision:
    """One human decision about one sighting."""

    outcome: ReviewOutcome
    reviewer: str
    decided_at: datetime
    individual_id: str | None = None
    cited_marks: tuple[str, ...] = ()  # e.g. "left ear notch", free text
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", ReviewOutcome(self.outcome))
        _text(self.reviewer, "reviewer")
        object.__setattr__(self, "decided_at", _utc(self.decided_at, "decided_at"))
        marks = tuple(self.cited_marks)
        for mark in marks:
            _text(mark, "cited mark")
        object.__setattr__(self, "cited_marks", marks)
        if not isinstance(self.note, str):
            raise SightingRecordError("note must be a string")
        if self.outcome in CONFIRMING:
            _text(self.individual_id, "individual_id for a confirmation")
        elif self.individual_id is not None:
            raise SightingRecordError(f"{self.outcome.value} must not name an individual")


@dataclass(frozen=True)
class Sighting:
    """One animal seen once on one survey, with its review history."""

    sighting_id: str
    survey_id: str
    observed_at: datetime
    latitude_deg: float
    longitude_deg: float
    position_source: PositionSource
    images: tuple[ImageRef, ...]
    detected_class: str  # proposed label (by a model or a person); not an identity
    track_id: str | None = None
    suggestions: tuple[MatchSuggestion, ...] = ()  # ranked, best first
    reviews: tuple[ReviewDecision, ...] = field(default=())

    def __post_init__(self) -> None:
        _text(self.sighting_id, "sighting_id")
        _text(self.survey_id, "survey_id")
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        lat = _number(self.latitude_deg, "latitude_deg")
        lon = _number(self.longitude_deg, "longitude_deg")
        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            raise SightingRecordError("latitude/longitude out of range")
        object.__setattr__(self, "latitude_deg", lat)
        object.__setattr__(self, "longitude_deg", lon)
        object.__setattr__(self, "position_source", PositionSource(self.position_source))
        images = tuple(self.images)
        if not images or not all(isinstance(i, ImageRef) for i in images):
            raise SightingRecordError("a sighting needs at least one ImageRef")
        object.__setattr__(self, "images", images)
        _text(self.detected_class, "detected_class")
        if self.track_id is not None:
            _text(self.track_id, "track_id")
        suggestions = tuple(self.suggestions)
        if not all(isinstance(s, MatchSuggestion) for s in suggestions):
            raise SightingRecordError("suggestions must be MatchSuggestion")
        object.__setattr__(self, "suggestions", suggestions)
        reviews = tuple(self.reviews)
        previous = self.observed_at
        for review in reviews:
            if not isinstance(review, ReviewDecision):
                raise SightingRecordError("reviews must be ReviewDecision")
            if review.decided_at < previous:
                raise SightingRecordError(
                    "reviews must be dated after the sighting and in order"
                )
            previous = review.decided_at
        object.__setattr__(self, "reviews", reviews)


def current_review(sighting: Sighting) -> ReviewDecision | None:
    """The latest human decision, or ``None``. Suggestions are never consulted."""
    return sighting.reviews[-1] if sighting.reviews else None


def current_outcome(sighting: Sighting) -> str:
    review = current_review(sighting)
    return UNREVIEWED if review is None else review.outcome.value


@dataclass(frozen=True)
class ConfirmationPolicy:
    """Minimum evidence for a confirmation. DEVELOPMENT PLACEHOLDERS.

    What counts as a confirmed individual is an open owner decision
    (PERCEPTION_PLAN.md). These defaults only stop an empty confirmation.
    """

    min_cited_marks: int = 1
    min_images: int = 1

    def __post_init__(self) -> None:
        for name in ("min_cited_marks", "min_images"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SightingRecordError(f"{name} must be a whole number >= 1")


def apply_review(
    sighting: Sighting,
    decision: ReviewDecision,
    known_individuals: Iterable[str],
    policy: ConfirmationPolicy | None = None,
) -> Sighting:
    """Return a copy with ``decision`` appended, or raise :class:`ReviewRefused`.

    ``known_individuals`` is the database's set of individual ids *other than*
    any founded by this sighting itself (see :func:`confirmed_individuals`).
    """
    policy = policy or ConfirmationPolicy()
    if not isinstance(decision, ReviewDecision):
        raise ReviewRefused("decision must be a ReviewDecision")
    latest = current_review(sighting)
    floor = latest.decided_at if latest else sighting.observed_at
    if decision.decided_at < floor:
        raise ReviewRefused("decision is dated before the sighting or the previous review")
    known = frozenset(known_individuals)
    if decision.outcome in CONFIRMING:
        if len(decision.cited_marks) < policy.min_cited_marks:
            raise ReviewRefused(
                f"confirmation cites {len(decision.cited_marks)} mark(s); "
                f"policy needs {policy.min_cited_marks}"
            )
        if len(sighting.images) < policy.min_images:
            raise ReviewRefused(
                f"sighting has {len(sighting.images)} image(s); policy needs {policy.min_images}"
            )
    if decision.outcome is ReviewOutcome.CONFIRMED_KNOWN and decision.individual_id not in known:
        raise ReviewRefused(f"individual {decision.individual_id!r} is not in the database")
    if decision.outcome is ReviewOutcome.CONFIRMED_NEW and decision.individual_id in known:
        raise ReviewRefused(f"individual {decision.individual_id!r} already exists")
    return replace(sighting, reviews=(*sighting.reviews, decision))


def confirmed_individuals(sightings: Iterable[Sighting]) -> dict[str, tuple[str, ...]]:
    """Map each confirmed individual id to its sighting ids (founding sighting first).

    Uses each sighting's *current* review only. Raises
    :class:`SightingRecordError` on duplicate sighting ids, an individual with
    no current founding sighting (e.g. the founding review was later changed)
    or with more than one.
    """
    founders: dict[str, list[str]] = {}
    members: dict[str, list[str]] = {}
    seen: set[str] = set()
    for sighting in sightings:
        if sighting.sighting_id in seen:
            raise SightingRecordError(f"duplicate sighting id {sighting.sighting_id!r}")
        seen.add(sighting.sighting_id)
        review = current_review(sighting)
        if review is None or review.outcome not in CONFIRMING:
            continue
        assert review.individual_id is not None
        target = founders if review.outcome is ReviewOutcome.CONFIRMED_NEW else members
        target.setdefault(review.individual_id, []).append(sighting.sighting_id)
    problems = [
        f"{ind!r} has {len(founders.get(ind, []))} founding sightings"
        for ind in sorted(set(founders) | set(members))
        if len(founders.get(ind, [])) != 1
    ]
    if problems:
        raise SightingRecordError("database integrity: " + "; ".join(problems))
    return {ind: (founders[ind][0], *members.get(ind, [])) for ind in sorted(founders)}


# --- JSON-compatible records -------------------------------------------------

_SIGHTING_KEYS = frozenset(
    {
        "schema_version", "sighting_id", "survey_id", "observed_at", "latitude_deg",
        "longitude_deg", "position_source", "images", "detected_class", "track_id",
        "suggestions", "reviews",
    }
)
_IMAGE_KEYS = frozenset({"uri", "sha256", "captured_at", "source"})
_SUGGESTION_KEYS = frozenset({"individual_id", "score", "model_version"})
_REVIEW_KEYS = frozenset(
    {"outcome", "reviewer", "decided_at", "individual_id", "cited_marks", "note"}
)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise SightingRecordError(f"{name} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SightingRecordError(f"{name} is not ISO 8601: {value!r}") from exc
    return _utc(parsed, name)


def _fields(record: Any, keys: frozenset[str], name: str, optional: frozenset[str]) -> dict:
    if not isinstance(record, Mapping):
        raise SightingRecordError(f"{name} must be an object")
    unknown = set(record) - keys
    missing = keys - optional - set(record)
    if unknown or missing:
        raise SightingRecordError(
            f"{name}: unknown fields {sorted(unknown)}, missing fields {sorted(missing)}"
        )
    return dict(record)


def _enum(enum: type[StrEnum], value: Any, name: str) -> Any:
    try:
        return enum(value)
    except ValueError as exc:
        raise SightingRecordError(f"{name}: unknown value {value!r}") from exc


def _list(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise SightingRecordError(f"{name} must be a list")
    return value


def sighting_to_record(sighting: Sighting) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sighting_id": sighting.sighting_id,
        "survey_id": sighting.survey_id,
        "observed_at": _iso(sighting.observed_at),
        "latitude_deg": sighting.latitude_deg,
        "longitude_deg": sighting.longitude_deg,
        "position_source": sighting.position_source.value,
        "images": [
            {"uri": i.uri, "sha256": i.sha256, "captured_at": _iso(i.captured_at),
             "source": i.source.value}
            for i in sighting.images
        ],
        "detected_class": sighting.detected_class,
        "track_id": sighting.track_id,
        "suggestions": [
            {"individual_id": s.individual_id, "score": s.score, "model_version": s.model_version}
            for s in sighting.suggestions
        ],
        "reviews": [
            {"outcome": r.outcome.value, "reviewer": r.reviewer, "decided_at": _iso(r.decided_at),
             "individual_id": r.individual_id, "cited_marks": list(r.cited_marks),
             "note": r.note}
            for r in sighting.reviews
        ],
    }


def sighting_from_record(record: Any) -> Sighting:
    """Strict inverse of :func:`sighting_to_record`; refuses unknown or missing fields."""
    data = _fields(record, _SIGHTING_KEYS, "sighting", frozenset({"track_id"}))
    version = data["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise SightingRecordError(f"unsupported schema_version {version!r}")
    images = []
    for raw in _list(data["images"], "images"):
        item = _fields(raw, _IMAGE_KEYS, "image", frozenset())
        images.append(
            ImageRef(
                uri=item["uri"], sha256=item["sha256"],
                captured_at=_parse_time(item["captured_at"], "image captured_at"),
                source=_enum(ImageSource, item["source"], "image source"),
            )
        )
    suggestions = [
        MatchSuggestion(**_fields(raw, _SUGGESTION_KEYS, "suggestion", frozenset()))
        for raw in _list(data["suggestions"], "suggestions")
    ]
    reviews = []
    for raw in _list(data["reviews"], "reviews"):
        item = _fields(raw, _REVIEW_KEYS, "review", frozenset({"individual_id", "note"}))
        reviews.append(
            ReviewDecision(
                outcome=_enum(ReviewOutcome, item["outcome"], "review outcome"),
                reviewer=item["reviewer"],
                decided_at=_parse_time(item["decided_at"], "decided_at"),
                individual_id=item.get("individual_id"),
                cited_marks=tuple(_list(item["cited_marks"], "cited_marks")),
                note=item.get("note", ""),
            )
        )
    return Sighting(
        sighting_id=data["sighting_id"], survey_id=data["survey_id"],
        observed_at=_parse_time(data["observed_at"], "observed_at"),
        latitude_deg=data["latitude_deg"], longitude_deg=data["longitude_deg"],
        position_source=_enum(PositionSource, data["position_source"], "position_source"),
        images=tuple(images), detected_class=data["detected_class"],
        track_id=data.get("track_id"), suggestions=tuple(suggestions), reviews=tuple(reviews),
    )
