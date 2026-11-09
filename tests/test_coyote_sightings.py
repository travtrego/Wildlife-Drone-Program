import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from coyote.perception.sightings import (
    UNREVIEWED,
    ConfirmationPolicy,
    ImageRef,
    ImageSource,
    MatchSuggestion,
    PositionSource,
    ReviewDecision,
    ReviewOutcome,
    ReviewRefused,
    Sighting,
    SightingRecordError,
    apply_review,
    confirmed_individuals,
    current_outcome,
    sighting_from_record,
    sighting_to_record,
)

T0 = datetime(2026, 11, 7, 7, 15, tzinfo=UTC)
EST = timezone(timedelta(hours=-5))


def image(n=0, **kw):
    args = dict(
        uri=f"survey-store://2026-11-07/IMG_{n:04d}.ARW",
        sha256=f"{n:064x}",
        captured_at=T0,
        source=ImageSource.RGB_STILL,
    )
    args.update(kw)
    return ImageRef(**args)


def sighting(sid="s1", **kw):
    args = dict(
        sighting_id=sid,
        survey_id="2026-11-07-island-park",
        observed_at=T0,
        latitude_deg=41.63,  # illustrative test value, not a surveyed location
        longitude_deg=-71.21,
        position_source=PositionSource.RTK_FIXED,
        images=(image(),),
        detected_class="coyote",
    )
    args.update(kw)
    return Sighting(**args)


def decision(outcome, minutes=60, individual_id=None, marks=("left ear notch",), **kw):
    return ReviewDecision(
        outcome=outcome,
        reviewer="Travis",
        decided_at=T0 + timedelta(minutes=minutes),
        individual_id=individual_id,
        cited_marks=marks,
        **kw,
    )


def confirm_new(s, ind="C-001", minutes=60, known=()):
    return apply_review(s, decision(ReviewOutcome.CONFIRMED_NEW, minutes, ind), known)


def confirm_known(s, ind="C-001", known=("C-001",)):
    return apply_review(s, decision(ReviewOutcome.CONFIRMED_KNOWN, individual_id=ind), known)


def reject(s, minutes=90, known=("C-001",)):
    return apply_review(s, decision(ReviewOutcome.NOT_A_COYOTE, minutes, marks=()), known)


# --- identity comes only from human review ----------------------------------


def test_suggestions_never_set_identity():
    s = sighting(suggestions=(MatchSuggestion("C-001", 0.99, "reid-test-0"),))
    assert current_outcome(s) == UNREVIEWED
    assert confirmed_individuals([s]) == {}


def test_latest_review_supersedes_and_history_is_kept():
    s = confirm_new(sighting())
    s = apply_review(s, decision(ReviewOutcome.NOT_IDENTIFIABLE, 90, marks=()), ["C-001"])
    assert current_outcome(s) == "not_identifiable"
    assert [r.outcome for r in s.reviews] == [
        ReviewOutcome.CONFIRMED_NEW,
        ReviewOutcome.NOT_IDENTIFIABLE,
    ]


def test_apply_review_returns_copy_and_leaves_original_unchanged():
    original = sighting()
    updated = confirm_new(original)
    assert original.reviews == ()
    assert len(updated.reviews) == 1


# --- refusals ------------------------------------------------------------------


def test_confirmation_requires_individual_id():
    with pytest.raises(SightingRecordError, match="individual_id"):
        decision(ReviewOutcome.CONFIRMED_KNOWN, individual_id=None)


@pytest.mark.parametrize("outcome", [ReviewOutcome.NOT_A_COYOTE, ReviewOutcome.NOT_IDENTIFIABLE])
def test_non_confirming_outcome_must_not_name_individual(outcome):
    with pytest.raises(SightingRecordError, match="must not name"):
        decision(outcome, individual_id="C-001")


def test_known_individual_must_exist():
    with pytest.raises(ReviewRefused, match="not in the database"):
        confirm_known(sighting(), "C-404")


def test_new_individual_must_not_exist():
    with pytest.raises(ReviewRefused, match="already exists"):
        confirm_new(sighting(), known=("C-001",))


def test_confirmation_without_cited_marks_refused():
    d = decision(ReviewOutcome.CONFIRMED_NEW, individual_id="C-001", marks=())
    with pytest.raises(ReviewRefused, match="cites 0 mark"):
        apply_review(sighting(), d, ())


def test_policy_can_require_more_images():
    d = decision(ReviewOutcome.CONFIRMED_NEW, individual_id="C-001")
    with pytest.raises(ReviewRefused, match="1 image"):
        apply_review(sighting(), d, (), ConfirmationPolicy(min_images=2))


def test_rejection_outcomes_need_no_marks():
    s = apply_review(sighting(), decision(ReviewOutcome.NOT_A_COYOTE, marks=()), ())
    assert current_outcome(s) == "not_a_coyote"


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_policy_rejects_non_positive_or_non_integer(bad):
    with pytest.raises(SightingRecordError):
        ConfirmationPolicy(min_cited_marks=bad)


def test_decision_before_sighting_refused():
    with pytest.raises(ReviewRefused, match="dated before"):
        apply_review(sighting(), decision(ReviewOutcome.NOT_A_COYOTE, minutes=-1, marks=()), ())


def test_decision_before_previous_review_refused():
    s = confirm_new(sighting(), minutes=60)
    with pytest.raises(ReviewRefused, match="dated before"):
        apply_review(s, decision(ReviewOutcome.NOT_A_COYOTE, minutes=30, marks=()), ["C-001"])


def test_refusal_leaves_sighting_unchanged():
    s = sighting()
    with pytest.raises(ReviewRefused):
        confirm_known(s, "C-404", known=())
    assert s.reviews == ()


# --- field validation ------------------------------------------------------


def test_naive_time_refused():
    with pytest.raises(SightingRecordError, match="timezone-aware"):
        sighting(observed_at=datetime(2026, 11, 7, 7, 15))


def test_times_normalised_to_utc():
    s = sighting(observed_at=datetime(2026, 11, 7, 2, 15, tzinfo=EST))
    assert s.observed_at == T0 and s.observed_at.tzinfo is UTC


@pytest.mark.parametrize(
    "kw",
    [
        {"latitude_deg": 91.0},
        {"longitude_deg": -181.0},
        {"latitude_deg": float("nan")},
        {"latitude_deg": True},
        {"images": ()},
        {"sighting_id": " "},
        {"detected_class": ""},
        {"track_id": ""},
    ],
)
def test_bad_sighting_fields_refused(kw):
    with pytest.raises(SightingRecordError):
        sighting(**kw)


@pytest.mark.parametrize("digest", ["abc", "G" * 64, "A" * 64, None])
def test_bad_checksum_refused(digest):
    with pytest.raises(SightingRecordError, match="sha256"):
        image(sha256=digest)


def test_non_finite_suggestion_score_refused():
    with pytest.raises(SightingRecordError, match="finite"):
        MatchSuggestion("C-001", float("inf"), "reid-test-0")


def test_out_of_order_review_history_refused_on_construction():
    late = decision(ReviewOutcome.NOT_A_COYOTE, 90, marks=())
    early = decision(ReviewOutcome.NOT_A_COYOTE, 30, marks=())
    with pytest.raises(SightingRecordError, match="in order"):
        sighting(reviews=(late, early))


# --- database integrity --------------------------------------------------------


def test_confirmed_individuals_groups_founder_first():
    a = confirm_new(sighting("a"))
    b = confirm_known(sighting("b"))
    c = sighting("c")
    assert confirmed_individuals([b, c, a]) == {"C-001": ("a", "b")}


def test_member_without_founder_is_integrity_error():
    # The founding review was later changed, leaving "b" pointing at nobody.
    a = reject(confirm_new(sighting("a")))
    b = confirm_known(sighting("b"))
    with pytest.raises(SightingRecordError, match="0 founding"):
        confirmed_individuals([a, b])


def test_two_founders_is_integrity_error():
    with pytest.raises(SightingRecordError, match="2 founding"):
        confirmed_individuals([confirm_new(sighting("a")), confirm_new(sighting("b"))])


def test_duplicate_sighting_id_is_integrity_error():
    with pytest.raises(SightingRecordError, match="duplicate"):
        confirmed_individuals([sighting("a"), sighting("a")])


# --- records -------------------------------------------------------------------


def full_sighting():
    s = sighting(
        track_id="t-17",
        images=(image(1), image(2, source=ImageSource.THERMAL_FRAME)),
        suggestions=(MatchSuggestion("C-001", 0.8, "reid-test-0"),),
    )
    return confirm_new(s)


def test_record_round_trip_through_json():
    s = full_sighting()
    record = json.loads(json.dumps(sighting_to_record(s)))
    assert record["schema_version"] == 1
    assert sighting_from_record(record) == s


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_unsupported_schema_version_refused(version):
    record = sighting_to_record(full_sighting())
    record["schema_version"] = version
    with pytest.raises(SightingRecordError, match="schema_version"):
        sighting_from_record(record)


def test_unknown_field_refused():
    record = sighting_to_record(full_sighting())
    record["identity"] = "C-001"  # an identity must come through reviews, not a side field
    with pytest.raises(SightingRecordError, match="unknown fields"):
        sighting_from_record(record)


def test_missing_nested_field_refused():
    record = sighting_to_record(full_sighting())
    del record["images"][0]["sha256"]
    with pytest.raises(SightingRecordError, match="missing fields"):
        sighting_from_record(record)


@pytest.mark.parametrize(
    "path,value",
    [
        (("observed_at",), "2026-11-07T07:15:00"),  # no offset
        (("observed_at",), "yesterday"),
        (("position_source",), "dead_reckoning"),
        (("reviews", 0, "outcome"), "auto_accepted"),
        (("images",), "IMG_0001.ARW"),
    ],
)
def test_bad_record_values_refused(path, value):
    record = sighting_to_record(full_sighting())
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(SightingRecordError):
        sighting_from_record(record)
