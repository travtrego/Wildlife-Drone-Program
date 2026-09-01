# Development Workflow

## Branching
Use short-lived feature branches for meaningful code changes.

Examples:
- `x500/mavsdk-takeoff-land`
- `x500/ros2-bridge`
- `fighter/mapping-mission-manager`
- `coyote/oakd-detection-node`
- `shared/telemetry-schema`

## Validation ladder
1. Static review / linting
2. Unit test
3. Simulation / SITL
4. Bench test with props removed when applicable
5. Controlled reference flight
6. Logged review
7. Promotion or release tag

## Commit philosophy
Prefer small commits that describe one engineering change. Avoid mixing configuration changes, refactors, and new flight behavior in one commit.

## Flight releases
Known-good flight configurations should eventually receive explicit tags rather than relying on the moving `main` branch.

Example future tags:
- `x500-flight-v0.1`
- `fighter-reference-v0.1`
- `coyote-perception-v0.1`

## Data policy
Do not commit raw flight logs, large videos, image datasets, trained-model artifacts, private credentials, or secrets directly to Git. Store lightweight metadata, test summaries, scripts, configuration, and links/manifests instead.

## Engineering evidence
Every important flight behavior should eventually have:
- requirement / intent
- configuration version
- test procedure
- pass/fail criteria
- result summary
- relevant log identifier
- follow-up action if failed
