# TunnelPilot — final lint fix

Based on GitHub HEAD `8c727ab2946c4642b9bc4fe662bb397535debdde`.

The current remote manifest contains `android:dataExtractionRules` but is missing the required `android:fullBackupContent` for `minSdk = 24`, and `backup_rules.xml` does not yet exist.

Copy the two files from this archive into the repository root, replacing:

- `app/src/main/AndroidManifest.xml`
- adding `app/src/main/res/xml/backup_rules.xml`

Then run:

```fish
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
./gradlew :app:lintDebug
```

Expected result: `:app:lintDebug` succeeds with 0 errors.
