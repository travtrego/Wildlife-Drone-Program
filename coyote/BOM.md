# Coyote component ledger

[bom.csv](bom.csv) is the maintained component/mass input ledger for the **October 15 screening configuration** (superseded in part by the 2026-10-18 owner decisions in [DECISIONS.md](DECISIONS.md): camera, thermal and motor rows are stale until recalculated), not an order list, weighed aircraft or inventory. Requirements and accepted choices belong in [DECISIONS.md](DECISIONS.md); methods/scenarios belong in [ENGINEERING_FEASIBILITY.md](ENGINEERING_FEASIBILITY.md).

## Schema and evidence

- `id`: stable assembly identifier; `quantity` × `mass_each_kg` gives installed modeled mass.
- `mass_evidence`: `catalogue_claim` means transcribed from the October 15 study with a source URL; `assumed` means a complete-assembly placeholder. Neither means weighed or integration-tested.
- `design_status`: `selected_candidate`, `baseline`, `preferred_proposal`, `candidate`, `model_only` or `unselected`. No value authorizes purchase.
- `ownership_status`, `installed_status`, `test_status`: independent of design status. Unknown inventory remains `unknown`; integration tests are `not_verified`.
- `power_idle_w`, `power_peak_w`, `dimensions_mm`, `interface`: blank means **unknown**, never zero. Replace with exact assembly specifications and evidence.
- `source_url`: source carried over from the study; blank means no exact assembly source.
- `source_checked_date`: date of the source study, not an independent vendor verification during this cleanup.
- `notes`: exclusions, unresolved variants, possible overlap and qualification gates.

All rows are physically present in this screening scenario; there are no mission-removable components. The battery row is one example, not simultaneous batteries for every scenario. Alternative packs and their modeled results remain in the feasibility report. Thermal and compute rows are finished-assembly placeholders, not bare-core/module masses.

## Updating inputs

Replace placeholders with exact SKU/revision, measured installed mass, source/evidence and power/interface data. Check kit inclusions and overlap before summing. A parts change requires recalculating the affected scenarios; old table results must be explicitly marked stale until reconciled.

No executable model has been introduced by this documentation cleanup. P5's regenerating model remains pending. The CSV is machine-readable groundwork, not an automated engineering qualification.
