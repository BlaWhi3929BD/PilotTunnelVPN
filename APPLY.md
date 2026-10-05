# TunnelPilot lint-zero fix

Base remote commit: 4f1cd2395e3daf9ae4b1efb0fa9d0fee1fbd4968.

This fixes the 12 lint errors from the latest report:
- kotlinx-coroutines-android 1.10.2 -> 1.11.0
- desugar_jdk_libs 2.0.3 -> 2.1.5
- add androidx.core:core-ktx 1.19.1 for the KTX SharedPreferences extensions
- add Android 12+ data extraction rules while keeping backups disabled
- add an explicit application icon
- convert SharedPreferences.edit() calls to the KTX edit extension

Because your working tree currently shows a modified file, use the ZIP as a file replacement rather than cherry-picking.

From the repository root:
  unzip -o /path/to/PilotTunnelVPN_lint_zero_fix.zip -d .

Then:
  ./gradlew :app:testDebugUnitTest
  ./gradlew :app:assembleDebug
  ./gradlew :app:lintDebug
