# Coyote perception and survey review

Coyote only (owner decision 2026-10-21: no perception or AI on the X500). Plan: [PERCEPTION_PLAN.md](../PERCEPTION_PLAN.md).

## `sightings.py`

**Candidate** sighting record and human-review rules (plan step 2, pipeline stage 6), so every survey can produce labelled data before any detector or re-identification model exists. Runs on the ground computer after flight; nothing here touches the vehicle.

- A `Sighting` holds one animal seen once on one survey: time (timezone-aware, stored as UTC), position and its source (RTK fixed/float, GNSS, manual), one or more `ImageRef`s (location of a file kept **outside Git** plus its SHA-256 and sensor: Sony still, zoom frame or thermal frame), the proposed class label, an optional track id, ranked machine `MatchSuggestion`s and an append-only list of `ReviewDecision`s.
- **Identity comes only from human reviews (R4).** `current_outcome` reads the latest review; suggestions are stored for the reviewer and for later top-1/top-5 evaluation, never as an identity.
- `apply_review` appends a decision or refuses it (`ReviewRefused`), never repairs it: confirmation without an individual id, an id on "not identifiable"/"not a coyote", "known" for an id not in the database, "new" for an existing id, a decision dated before the sighting or the previous review, or fewer cited marks/images than `ConfirmationPolicy`.
- `confirmed_individuals` checks the whole set: unique sighting ids and exactly one current founding ("new") sighting per individual.
- `sighting_to_record` / `sighting_from_record` give a strict JSON-compatible dict (`schema_version` 1; unknown or missing fields refused).

Storage was decided by the owner on 2026-11-12: a local SQLite file for records, imagery on an external hard drive ([DECISIONS.md](../DECISIONS.md)); no storage code exists yet. Still open: database table layout, backup copy, and what counts as a confirmed individual (both owner decisions, PERCEPTION_PLAN). `ConfirmationPolicy` defaults (at least one cited mark and one image) are **development placeholders**. The reviewer field is a name supplied by the review tool; code cannot prove a person decided. Nothing here shows that any camera or model can identify individual coyotes; the usable-still check on real survey imagery comes first.

Evidence status: **unit-tested only** (`tests/test_coyote_sightings.py`). No review tool, storage, real imagery or survey data exists yet.
