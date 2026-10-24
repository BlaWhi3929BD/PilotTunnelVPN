# TunnelPilot

TunnelPilot is an Android-first free WireGuard VPN client. The product goal is a simple VPN that can be free with in-app advertising, while keeping VPN traffic handling separate from advertising and analytics.

## What is implemented (v0.2.0)

- Native Android VPN flow using WireGuard Android Tunnel Library (`minSdk = 26`, `targetSdk = 35`).
- Encrypted local storage for the client configuration, WireGuard private key, and device token with Android Keystore (`AES/GCM/NoPadding`).
- Full-device routing mode (`ALL_APPS`).
- Per-app routing mode (`SELECTED_APPS`) using WireGuard's Android `IncludedApplications` support, failing closed when the effective installed allowlist is empty.
- Searchable installed-app selector with active selection counter and quick clear.
- Live RX/TX counters, permission diagnostics, and return-traffic/handshake hints while connected.
- Configuration validation before storage and preserved local `Provisioned` state across transient Control Plane errors.
- Explicit reconnect flow when routing rules change, manual tunnel reconnect, and `ConnectivityManager` network-change state synchronization.
- Control-plane provisioning that generates the client key locally, registers only the public key, and enforces HTTPS for non-loopback endpoints in Release builds.
- Persistent SQLite storage (`0600` file permissions) for device allocation, SHA-256 device authentication tokens, and online backup/restore with integrity checks (M2.3a).
- Authenticated WireGuard client key rotation with pending-key crash/timeout recovery and failure-safe rollback (M2.3b).
- Fail-closed device revocation supporting both admin Bearer tokens (`TUNNELPILOT_CONTROL_PLANE_TOKEN`, strictly isolated from open device enrollment) and device self-revocation (`X-Device-Token`) with failure-safe gateway cleanup (M2.3c).
- Gateway peer state reconciliation (`GET /v1/peers` + `POST /v1/servers/reconcile` with non-destructive `dry_run=true` support, empty/corrupt SQLite guards, and startup reconciliation) (M2.3d).
- Local device identity reset & recovery in Android Setup UI, preserving credentials on server revoke failure with an explicit offline emergency reset option (M2.3e).
- Live gateway catalog, health & capacity inspection from the Android client (`GET /v1/servers`) with loading, cached/stale, and empty state diagnostics (M2.4a).
- Production startup validation on both Control Plane and Gateway Agent (token separation, HTTPS enforcement, managed-interface verification).
- Debug-only remote ADB CLI (`DebugCliProvider` + `./scripts/tp-adb-cli.sh`) for automated device testing over USB, completely excluded from Release manifests and artifacts.
- TCP MSS clamping and NAT forwarding tooling for reliable high-speed data plane.

## Important product decision

"Selected apps" mode means the VPN tunnel stays active while only the selected applications are allowed through the VPN; non-selected applications use the regular network route. Android's public VPN API supports an allow-list that is fixed when the VPN connection is established; changing it requires establishing a new VPN connection. This is more reliable and more policy-friendly than trying to monitor which app is foregrounded and repeatedly starting/stopping the VPN.

## Roadmap & Release Scope

### Included in Current Release (v0.2.0)
- [x] M1 — Native Android WireGuard client, Keystore storage, All-Apps & Selected-Apps routing
- [x] M2.1 / M2.2 — Linux WireGuard Gateway Agent with automated forwarding, TCP MSS clamping, health & capacity reporting
- [x] M2.3a — Persistent SQLite state, SHA-256 device authentication tokens, backup/restore & `0600` permissions
- [x] M2.3b — Authenticated client key rotation with timeout recovery and without exposing private keys
- [x] M2.3c / M2.3d / M2.3e — Admin & self-service revocation, non-destructive gateway reconciliation, and Android identity recovery
- [x] M2.4a / M2.4b — Multi-server dynamic SQLite catalog, server pinning, migration API with rollback, tombstone reconciliation, and Android region/server selector
- [x] M3 (Core & M3.5) — First-run onboarding guidance, connection/permission/handshake diagnostics, network-change handling, and Selected Apps category presets (Browsers, Messengers, Media)
- [x] M4 — In-app monetization: GDPR/Play Privacy & Ad choices dialog, isolated Compose AdContainer (zero access to VPN traffic), rewarded 24h Premium unlock with automatic expiry
- [x] M5 (Production & Release Readiness) — Hardened systemd services (with `CAP_NET_ADMIN`), automated daily SQLite backup timer, `infra/deploy-production.sh`, Google Play compliance package (`docs/PRIVACY_POLICY.md`, `docs/PLAY_STORE_SUBMISSION_GUIDE.md`, `docs/RELEASE_SIGNING_GUIDE.md`), and verified Release APK & AAB build pipeline

### Next Steps for Repository Owner (Public Play Store Rollout)
- [ ] Provide private release keystore via `keystore.properties` (see `docs/RELEASE_SIGNING_GUIDE.md`) to build signed AAB
- [ ] Host `docs/PRIVACY_POLICY.md` on public HTTPS URL
- [ ] Submit `app-release.aab` to Google Play Console Internal/Closed Testing track (see `docs/PLAY_STORE_SUBMISSION_GUIDE.md`)

## Security rules

Never commit WireGuard private keys, server private keys, API tokens, signing keys, ad credentials, or production database secrets.
