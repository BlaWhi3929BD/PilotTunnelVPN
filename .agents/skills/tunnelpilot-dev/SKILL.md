---
name: tunnelpilot-dev
description: Instructions and guidelines for TunnelPilot repository navigation, commands, testing, and safe branch discipline.
---

# TunnelPilot Development Guide

## Environment
- Python virtualenv: `.venv/bin/python`, `.venv/bin/pytest`
- Android build: `./gradlew :app:assembleDebug :app:lintDebug`
- Unit tests: `./gradlew :app:testDebugUnitTest`
- Gateway: Linux WireGuard interface `tunnelpilot0` (10.67.0.1/24)

## Validation Checklist
1. `.venv/bin/pytest server/tests -q`
2. `./gradlew :app:testDebugUnitTest`
3. `./gradlew :app:assembleDebug`
4. `./gradlew :app:lintDebug`
Never claim checks passed without executing them.
