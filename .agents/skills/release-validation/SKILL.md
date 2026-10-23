---
name: release-validation
description: Pre-commit and pre-release verification checklist for code, tests, lint, and Git status.
---

# Release Validation Checklist

Before committing or releasing:
1. Run `pytest server/tests -q`.
2. Run `./gradlew :app:testDebugUnitTest`.
3. Run `./gradlew :app:assembleDebug`.
4. Run `./gradlew :app:lintDebug`.
5. Check `git status --short` to ensure no temporary files, database files, or secrets are staged.
