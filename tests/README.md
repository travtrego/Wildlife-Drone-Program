# Tests

This directory holds reusable automated and procedural validation assets.

Planned categories:
- unit tests for mission logic
- interface tests for MAVSDK / ROS 2 adapters
- configuration validation
- message-schema tests
- simulation regression tests
- sensor-data parsing tests
- command-guard / safety tests

Physical flight-test procedures belong in platform-specific `flight_tests/` or documentation, while reusable automated checks belong here.
