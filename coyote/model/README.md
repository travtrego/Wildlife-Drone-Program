# Coyote mass and endurance model

Regenerates the hover-endurance screening table from [`../bom.csv`](../bom.csv) whenever a part changes (proposal P5, adopted 2026-10-18). **Screening estimates only**: catalogue claims, review claims and placeholders, not weighed mass or flight endurance. Requirements R5, R9 and R10 live in [DECISIONS.md](../DECISIONS.md).

## Run

From the repository root:

```bash
python -m coyote.model.endurance                       # Oct 15 configuration, Oct 15 assumptions
python -m coyote.model.endurance --profile conservative \
  --changes coyote/model/decisions_2026-10-18.csv      # owner decisions, P4 assumptions
```

## Inputs

| File | What it holds |
|---|---|
| [`../bom.csv`](../bom.csv) | Component ledger; its `battery` row is replaced by each candidate pack |
| [`batteries.csv`](batteries.csv) | Candidate 12S packs from the feasibility study; blank `continuous_a` means not transcribed, and R10 then reports `unknown` |
| [`x8_original_46v.csv`](x8_original_46v.csv) | Original X8 bench thrust/power points. The model interpolates linearly and refuses to extrapolate |
| [`decisions_2026-10-18.csv`](decisions_2026-10-18.csv) | remove/add/set_mass rows applying the 2026-10-18 decisions: split camera (P1), Boson+ dropped, X8 G2 mass (P2) |

Profiles: `screening` (120 W load, 80% usable, no margin; reproduces ENGINEERING_FEASIBILITY.md section 3 exactly) and `conservative` (the review's P4: 150 W, 70% usable for about a 25% landing reserve, +10% wind/maneuver margin, +0.65 kg mounts/harness).

## Known gaps

- **X8 G2 power curve not transcribed.** The decision scenario uses X8 G2 *mass* with the *original X8* power curve as a stand-in. Add the G2 46 V table as a new curve CSV and pass `--curve` to replace it.
- Split-camera masses are the October 15 review's claims (stills package about 1.1 kg including the camera body; ZT30 870 g), not vendor-verified assemblies.
- Most packs lack a transcribed continuous-current rating, so R10 is unknown for them.
- Hover only: no climb, cruise, gust, temperature, voltage sag or battery-ageing model.

## Current output (2026-10-18)

Decisions applied, `conservative` profile:

| Battery | Takeoff mass | Under 55 lb (R9) | Hover power | Hover current | Current rule (R10) | Minutes | R5 >= 20 min |
|---|---:|---|---:|---:|---|---:|---|
| Tattu 12S 22Ah semi-solid | 22.627 kg (49.9 lb) | yes | 2.458 kW | 55 A | NO | 16.7 | NO |
| Tattu Neo 26Ah 12S | 23.386 kg (51.6 lb) | yes | 2.564 kW | 58 A | unknown | 18.9 | NO |
| Tattu Neo 33Ah 12S | 24.354 kg (53.7 lb) | yes | 2.699 kW | 61 A | unknown | 22.8 | yes |
| Tattu Neo 36Ah 12S | 24.707 kg (54.5 lb) | yes | 2.748 kW | 62 A | unknown | 24.4 | yes |
| Conventional Tattu 22Ah smart | 25.206 kg (55.6 lb) | NO | 2.818 kW | 63 A | unknown | 14.6 | NO |

Decisions applied, `screening` profile:

| Battery | Takeoff mass | Under 55 lb (R9) | Hover power | Hover current | Current rule (R10) | Minutes | R5 >= 20 min |
|---|---:|---|---:|---:|---|---:|---|
| Tattu 12S 22Ah semi-solid | 21.977 kg (48.5 lb) | yes | 2.122 kW | 48 A | NO | 22.1 | n/a |
| Tattu Neo 26Ah 12S | 22.736 kg (50.1 lb) | yes | 2.219 kW | 50 A | unknown | 25.0 | n/a |
| Tattu Neo 33Ah 12S | 23.704 kg (52.3 lb) | yes | 2.341 kW | 53 A | unknown | 30.0 | n/a |
| Tattu Neo 36Ah 12S | 24.057 kg (53.0 lb) | yes | 2.386 kW | 54 A | unknown | 32.2 | n/a |
| Conventional Tattu 22Ah smart | 24.556 kg (54.1 lb) | yes | 2.449 kW | 55 A | unknown | 19.1 | n/a |

Rerun after any ledger change; these tables are not maintained by hand.
