# TunnelPilot final lint fix

This fixes the remaining `DataExtractionRules` lint error for minSdk 24 by adding the legacy `android:fullBackupContent` resource alongside `android:dataExtractionRules`.

Copy these files into the repository root:

- `app/src/main/AndroidManifest.xml`
- `app/src/main/res/xml/backup_rules.xml`

Then run:

```fish
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
./gradlew :app:lintDebug
```

Expected: lint reports 0 errors.
