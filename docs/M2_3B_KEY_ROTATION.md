# M2.3b — device key rotation

M2.3b adds authenticated client WireGuard key rotation without exposing private keys to the control plane.

## Server flow

1. Android authenticates with its existing device token.
2. Control plane validates the new public key and keeps the existing device address/server assignment.
3. The gateway peer for the old public key is removed.
4. The new public key is provisioned with the same `/32`.
5. Persistent device state is updated.
6. On a storage failure, the control plane attempts to restore the old gateway peer.

The device token is intentionally preserved across key rotation so key rotation does not become an identity reset.

## Android flow

`MainViewModel.rotateDeviceKey()` generates a new private key locally, sends only the new public key, stores the new private key encrypted with Android Keystore, and rebuilds the encrypted WireGuard configuration. If local persistence fails after server rotation, the client attempts to rotate back to the old public key.

The UI does not expose the rotation action yet; the API/lifecycle path is intentionally validated before adding another control to the product surface.

## Validation

```fish
pytest server/tests -q
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
./gradlew :app:lintDebug
```
