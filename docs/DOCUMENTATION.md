# Documentation ownership

Each kind of fact has one maintained home. Other pages summarize briefly and link to it.

| Information | Maintained home | Update rule |
|---|---|---|
| Program stage and next blocker | [STATUS.md](STATUS.md) | Cite evidence and review date; link trackers |
| Test results and evidence boundaries | [VALIDATION.md](VALIDATION.md) | Record exact revision; retain dated detailed reports |
| Coyote requirements, choices, gates | [DECISIONS.md](../coyote/DECISIONS.md) | Separate requirements, candidates, proposals and accepted changes |
| Coyote component quantities/mass/status | [bom.csv](../coyote/bom.csv), schema in [BOM.md](../coyote/BOM.md) | Exact variant/source; unknown ownership stays unknown |
| Screening calculation method/results | [ENGINEERING_FEASIBILITY.md](../coyote/ENGINEERING_FEASIBILITY.md) | Reconcile with ledger before publishing changed results |
| Detailed integration rationale/history | [PLATFORM_MASTER_REPORT.md](../coyote/PLATFORM_MASTER_REPORT.md) | Link current decisions/model; keep historical date/context |
| External review inputs and dispositions | [Review register](../coyote/reviews/README.md) | Preserve supplied source; record acceptance separately |
| Software architecture and promotion | [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) | Distinguish planned modules from implemented code |

README files are navigation and orientation, not parallel BOMs or copies of every decision. Agent instructions describe how to work and point to the requirements; they do not maintain a second requirements list. Issues track execution and discussion; accepted engineering changes must be recorded in the appropriate file.

## Changes to engineering inputs

1. Record the source, exact SKU/revision and evidence class.
2. Obtain owner agreement before changing a requirement or adopting a pending alternative.
3. Update the component ledger and affected calculation together.
4. Update the decision record, then the short status summary if the stage changed.
5. Link evidence rather than presenting a proposed test as completed.

Preserve dated external reports as received. Append dispositions in the register; do not silently rewrite the source into an accepted design. Historical reports can contain superseded figures; their notices must point readers to the current maintained record.
