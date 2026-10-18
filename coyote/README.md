# Coyote

Six-rotor wildlife research and multi-sensor robotics aircraft. **Procurement HOLD.**

## Read in this order

1. [Requirements, decisions and open gates](DECISIONS.md) — authoritative current design record.
2. [Component ledger guide](BOM.md) and [CSV](bom.csv) — candidate components, quantities, mass assumptions and unknowns.
3. [Engineering feasibility](ENGINEERING_FEASIBILITY.md) — screening method/results and limitations.
4. [Platform master report](PLATFORM_MASTER_REPORT.md) — detailed integration rationale, historical decisions and vendor questions.
5. [Review register](reviews/README.md) — supplied desk review, proposals and unresolved claims.
6. [Program validation evidence](../docs/VALIDATION.md) — simulation versus hardware qualification.

The full sensor suite stays permanently installed. EFT E616P is the preferred engineering candidate, conditional on fit and performance. No supplier rating, estimated mass or modeled flight time closes the purchase gate.

Coyote-specific perception, fusion, mounting and aircraft configuration remain planned. Software is inherited from `shared/` only after appropriate validation; [architecture](../docs/ARCHITECTURE.md) defines the flight-control boundary.

## Where to record changes

Use [documentation ownership](../docs/DOCUMENTATION.md). Keep requirements in DECISIONS.md, component inputs in bom.csv and calculated scenarios in ENGINEERING_FEASIBILITY.md. This page deliberately contains no duplicate dimension or endurance tables.
