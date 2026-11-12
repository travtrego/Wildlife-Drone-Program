# Coyote perception plan: machine learning for individual identification

**Status: plan only.** No perception model, dataset or survey result exists yet. The only code is a candidate sighting record and human-review rules for step 2 ([`perception/sightings.py`](perception/README.md), unit-tested only). Requested by the owner on 2026-11-08: Coyote will use machine learning (ML) and computer vision (CV) to help identify individual coyotes. Requirements stay in [DECISIONS.md](DECISIONS.md) (R4: weekly survey population database of individually identified coyotes, identification human-confirmed). This page describes *how* we intend to meet R4; it does not change it.

Coyote only. The X500 carries no perception or AI (owner decision 2026-10-21).

## Goal

Every weekly survey produces sightings that a person can confirm as a known individual or a new one, with the evidence (photos, time, place) stored in the population database. ML finds animals, picks good shots and *suggests* who each animal is; a person makes the identification.

## Pipeline

| Stage | What it does | Where it runs | Candidate approach (not selected) |
|---|---|---|---|
| 1. Detect | Find animals in the zoom/thermal gimbal video | Jetson, live | Small YOLO-class detector, TensorRT-optimised; classes coyote, fox, deer, dog, person, other |
| 2. Track | Keep one track ID per animal across frames; add range from depth/LiDAR | Jetson, live | ByteTrack-class tracker; OAK-D / LiDAR range fused by time and calibration |
| 3. Shot quality | Judge pose (side-on, head visible), focus, occlusion by vegetation | Jetson, live | Lightweight pose/quality classifier |
| 4. Capture | Trigger Sony stills when a track has a good view | Jetson, live | Rule on quality score; stills tagged with time, GNSS/RTK position, track ID |
| 5. Re-identify | Compare the animal's ear notches, scars, coat and face against known individuals; rank likely matches | Ground computer, after flight | Metric-learning re-ID model (embedding + nearest neighbours) |
| 6. Confirm | Person accepts a match, marks a new individual or rejects | Ground computer | Review tool; every decision becomes labelled training data |

Live stages (1–4) only *observe and propose*. Any movement they want (hold, reposition for a better angle, back off) goes as a request through the [action gate](autonomy/README.md) under operator delegation (R6); PX4 flies and the pilot can always override. Re-ID runs after the flight because it needs the full database, not the flight loop.

## Data plan

- **Detection:** start from public wildlife/camera-trap and aerial datasets, then fine-tune on our own RGB and thermal survey footage of Island Park and the nearby marshes.
- **Re-identification:** needs our own labelled photos of individual coyotes, many sightings per animal across weeks, light and seasons. There is no shortcut; the weekly surveys collect it. Expect re-ID suggestions to be weak until a few dozen confirmed sightings exist.
- **Labelling:** detections boxed and classed; individuals named only by human confirmation. Keep a record of who confirmed what and when.
- **Storage:** raw imagery, datasets and model weights stay **outside Git** ([data policy](../docs/DEVELOPMENT_WORKFLOW.md)). Git holds code, schemas, dataset manifests and evaluation summaries.

## How we will know it works

| Measure | What it shows | Gate |
|---|---|---|
| Detection recall/precision on held-out survey footage, RGB and thermal | Finds coyotes without flooding the operator | Before using detections to propose movements |
| Track continuity | One animal is not split into many tracks | Before capture triggers |
| Usable-still rate | Share of tracks yielding a still where marks are readable | **First:** decides whether ID is feasible at all |
| Re-ID top-1 / top-5 match rate against human-confirmed IDs | Suggestions save the reviewer time | Before showing suggestions as defaults |
| Jetson frame rate, latency, power and temperature with all sensors running | Fits R7 concurrency budget | Before flight use |
| Disturbance observations (animal reaction vs stand-off distance) | Approach rules are acceptable | Before any reposition proposals near animals |

## Order of work

1. **Feasibility first:** fly first real surveys (manual or simple waypoint) and check whether identifying marks are readable at a non-disturbing distance. This is the open risk in DECISIONS.md (resolution test skipped). If marks are not readable, revisit optics before building ML.
2. Sighting/database schema and the review tool (stage 6), so every survey from day one produces labelled data. *Candidate record and review rules: [`perception/sightings.py`](perception/README.md) (unit-tested only); storage decided 2026-11-12 (local SQLite file, imagery on an external drive); storage code and review tool not started.*
3. Offline detector + tracker on recorded footage; then on the Jetson in replay.
4. Shot-quality scoring and capture triggering in simulation/replay.
5. Re-ID model once enough confirmed sightings exist.
6. Live proposals through the action gate: SITL first, then bench, then controlled flights (validation ladder).

## Risks and unknowns

- Optics may not resolve marks at a safe stand-off distance (biggest risk).
- Coyote coats are less distinctive than spotted species; individual re-ID accuracy from aerial images is unproven. Fox or camera-trap results are not evidence for aerial coyote ID.
- Thermal images help detection but carry little identity information.
- Jetson Orin NX capacity with every sensor running is unmeasured.
- Permits, wildlife-disturbance rules and site access for Island Park and marshes.

## Owner decisions needed later

- What counts as a confirmed individual (which marks, how many matching photos).
- Database table layout and backup copy. *Storage decided 2026-11-12: a local SQLite file for records, imagery on an external hard drive ([DECISIONS.md](DECISIONS.md)).*
- Minimum stand-off distance and approach rules near animals.
- Whether re-ID suggestions may ever be accepted automatically. Until decided, every ID is human-confirmed (R4).
