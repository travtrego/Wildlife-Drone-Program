# Shared Autonomy Stack

Reusable code is intended to be promoted from platform-specific development after appropriate validation.

**Implemented today:** package initializers and `autonomy/sitl.py` configuration helpers. The directories below are a future architecture sketch, not existing modules. The helper's presence does not establish hardware/flight qualification; see [validation evidence](../docs/VALIDATION.md).

Planned modules:

```text
shared/
├── mission_manager/   # mission state, objectives, task sequencing
├── telemetry/         # normalized vehicle state / link interfaces
├── logging/           # structured experiment and mission logging
├── safety/            # software-side safety checks and command guards
└── messages/          # common ROS 2 / internal message definitions
```

## Promotion rule
A module should move here only when:
1. its interface is stable,
2. platform-specific assumptions have been removed or parameterized,
3. automated tests exist where practical,
4. bench/simulation tests pass,
5. any required flight validation is documented.

`shared/` is intended to become the program's reusable autonomy product rather than a dumping ground for miscellaneous utilities.
