# TunnelPilot 0.2 update

This change is designed to be overlaid on the existing local checkout. Keep your existing `gradlew`, `.gradle`, `local.properties`, and `.git` directory.

## Apply

Extract the source archive into the repository root and overwrite existing files.

## Verify

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:lintDebug
./gradlew :app:assembleDebug
```

The Android app now has:

- full-device and selected-app routing modes;
- encrypted client config storage using Android Keystore;
- searchable app selection;
- reconnect-required state when routing rules change;
- RX/TX counters while connected;
- stronger WireGuard config validation;
- a control-plane development skeleton under `server/`.

The first production gateway and control-plane provisioning are intentionally not included in this release because they require real infrastructure, secrets, and operational policy decisions.
