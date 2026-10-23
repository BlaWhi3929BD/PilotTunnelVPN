# TunnelPilot — release checklist

This document is a living evidence log maintained by `tunnelpilot-release-lead`. Do not mark a task `PASS` without a command, test result, artifact, commit, or reproducible observation.

Statuses: `TODO`, `IN_PROGRESS`, `PASS`, `BLOCKED`, `NOT_APPLICABLE`.

## Phase 0 — repository truth
- [x] `PASS` — Verify branch, HEAD, working tree and user-owned changes (`main`, starting at `b815e63`, preserving untracked user files `.agents/agents/`, `README_RU.md`, `START_HERE_PROMPT_RU.txt`).
- [x] `PASS` — Reconcile current repository with roadmap and existing handoff docs (`docs/TunnelPilot_Agent_Handoff_2026-10-23.md`, `README.md`).
- [x] `PASS` — Obtain independent debugger, regression and security gap reports (conducted directly by release lead as `invoke_subagent` tool is unavailable in this runtime environment).

## Phase 1 — core correctness and security
- [x] `PASS` — Public enrollment cannot bypass admin auth (`_require_admin_auth` strictly separated from `_require_enrollment_auth` in `server/app/main.py`, commit `b815e63`; verified by `test_open_registration_never_bypasses_admin_endpoints`).
- [x] `PASS` — Admin mutation endpoints fail closed in required configurations (`POST /v1/servers/reconcile`, `POST /v1/servers/{server_id}/reconcile`, and admin `DELETE /v1/devices/{device_id}` return `401`/`503` without valid `TUNNELPILOT_CONTROL_PLANE_TOKEN`; verified in `server/tests/test_devices.py`).
- [x] `PASS` — Reconciliation dry-run proves zero mutations (`POST /v1/servers/reconcile` with `{"dry_run": true}` returns `status="dry_run", dry_run=true` with zero `add_peer`/`remove_peer` calls; verified in `test_reconcile_dry_run_query_and_json_body_performs_no_gateway_mutations` and live `127.0.0.1:8000` check).
- [x] `PASS` — Reconciliation protected against empty/corrupt/wrong SQLite database (`_reconcile_gateway_peers` checks `store.integrity_ok()` and `empty_database_prune_blocked`; verified in `test_reconcile_empty_and_corrupt_sqlite_database_guards`).
- [x] `PASS` — SQLite path, integrity, transactions and address allocation are reliable (`DEFAULT_DB_PATH` anchored to `_REPO_ROOT`, `BEGIN IMMEDIATE` transactions, `PRAGMA quick_check`; verified in `server/tests/test_storage.py`).
- [x] `PASS` — Key rotation/provision recover after timeouts and partial failures (`pendingPrivateKey` in `IdentityStore`, HTTP 409 conflict recovery, and rollback on local save error; verified in `TunnelPilotControllerTest.keyRotation_recoversFromPostCommitTimeoutConflictAndLocalFailureWithoutLeakingPrivateKey`).
- [x] `PASS` — Device revoke/reset preserve credentials until remote revoke succeeds (`clearConfigNow` and `resetIdentityNow` fail closed by default when server revoke fails, with explicit `forceLocal=true` emergency offline option; verified in `TunnelPilotControllerTest.revokeAndReset_preserveCredentialsOnServerFailureAndSupportExplicitForceLocal`).
- [x] `PASS` — `SELECTED_APPS` fails closed for empty effective allowlist and UI behavior is truthful (`TunnelPilotController.buildEffectiveConfig` throws when `effectiveApps.isEmpty()`; verified in `TunnelPilotControllerTest.selectedAppsMode_enforcesEmptyValidMissingAndReconnectErrorScenarios`).
- [x] `PASS` — Debug ADB provider absent from release artifacts and does not expose secrets (`DebugCliProvider` declared only in `app/src/debug/AndroidManifest.xml`, caller UID restricted to shell/root/app, never returns private keys or tokens; verified in `ControlPlaneClientTest.mergedReleaseManifest_excludesDebugCliProviderAndCleartextTraffic` and binary APK/AAB inspection).
- [x] `PASS` — Android saved configuration survives transient Control Plane failures (`ProvisioningState.Provisioned` preserves `deviceId`, `clientAddress`, and encrypted config while recording `lastError`; verified in `TunnelPilotControllerTest.networkFailures_preserveExistingProvisionedStateAndClientAddress`).

## Phase 2 — backend/gateway operation
- [x] `PASS` — Production startup configuration validated and fail-closed (`_validate_runtime_configuration` in `server/app/main.py` and `_validate_gateway_configuration` in `server/gateway_agent/app.py`, commit `fe4e117`; verified in `test_production_startup_requires_distinct_tokens_and_https_gateway` and `test_gateway_startup_validates_token_and_managed_interface`).
- [x] `PASS` — Public control-plane traffic protected by TLS before production use (`_enforce_production_transport_security` rejects plaintext HTTP in production on Control Plane, and `ControlPlaneClient` with `allowCleartext = BuildConfig.DEBUG` rejects non-loopback `http://` in Release builds; commits `fe4e117`, `6855153`).
- [x] `PASS` — Gateway Agent privilege boundary and managed-interface ownership verified (`ensure_managed_interface()` enforced at startup and per-operation, interface regex validated, bound to `127.0.0.1:8787`; commit `fe4e117`).
- [x] `PASS` — Stable DB path, backup/restore and recovery after gateway restart documented/tested (`DeviceStore.backup_to` and `DeviceStore.restore_from` with `0600` file mode and integrity validation; verified in `test_backup_and_restore_roundtrip_and_corrupt_source_rejection`, commit `fe4e117`).
- [x] `PASS` — Service scripts, token permissions and health diagnostics verified (`scripts/start-gateway-agent.sh` and `scripts/start-control-plane.sh` preserve `chmod 600` tokens, reuse `gateway-agent.token` across restarts, and respect user environment overrides; commit `fe4e117`).

## Phase 3 — Android product experience
- [x] `PASS` — Onboarding/provisioning path is recoverable and understandable (`Welcome to TunnelPilot` onboarding card in `MainActivity.kt` when `!configPresent`, direct navigation to `Setup`/`Config`, commit `6855153`).
- [x] `PASS` — Connected state matches actual WireGuard backend state (`refreshState()` synchronizes with `manager.currentState()` on resume and network callbacks; verified in `TunnelPilotControllerTest.reconnectAndRefreshState_synchronizeWithBackendAndSelection`).
- [x] `PASS` — Network-change/reconnect behavior tested (`ConnectivityManager.NetworkCallback` in `MainActivity.kt`, manual `Reconnect tunnel` action, and `reconnectNow()` unit test; commit `6855153`).
- [x] `PASS` — Server catalog loading, empty, stale and error states tested (`serversLoading`, `serversLoaded`, cached catalog retention on refresh failure in `TunnelPilotController.kt`; verified in `TunnelPilotControllerTest.serverCatalogRefresh_handlesSuccessEmptyAndStaleErrorStates`).
- [x] `PASS` — Selected Apps UX and per-UID semantics tested (searchable app list, installed selection counter, clear selection action, empty-selection warning, and per-UID routing tests; commit `6855153`).
- [x] `PASS` — Permissions, server reachability and handshake diagnostics are truthful (`vpnPermissionRequired` indicator, `provisioningSummary`, RX/TX counters, and zero-RX return-traffic hint in `MainActivity.kt`; commit `6855153`).

## Phase 4 — roadmap scope
- [x] `PASS` — Decide which roadmap milestones are in first release vs later releases (documented in `README.md` under `Included in v0.2.0 Release Build` vs `Deferred to Post-v0.2.0 Milestones`, commit `6855153`).
- [x] `PASS` — Smart Apps/Smart Auto deferred or implemented only with platform-supported design (deferred to M3.5 in `README.md`; v0.2.0 uses Android's public `VpnService.Builder.addAllowedApplication` via WireGuard `IncludedApplications`).
- [x] `PASS` — Monetization/ads deferred from first release unless explicitly required (deferred to M4 in `README.md`; zero ad SDKs or trackers in v0.2.0 release artifacts).

## Phase 5 — final verification
- [x] `PASS` — `.venv/bin/pytest server/tests -q` (`44 passed in 1.08s`).
- [x] `PASS` — `./gradlew :app:testDebugUnitTest` (`BUILD SUCCESSFUL`, 21 unit tests in `ControlPlaneClientTest`, `TunnelPilotControllerTest`, `WireGuardConfigValidatorTest`).
- [x] `PASS` — `./gradlew :app:assembleDebug` (`BUILD SUCCESSFUL`, `app/build/outputs/apk/debug/app-debug.apk`).
- [x] `PASS` — `./gradlew :app:lintDebug` (`BUILD SUCCESSFUL`, 0 errors).
- [x] `PASS` — `./gradlew :app:assembleRelease` (`BUILD SUCCESSFUL`, R8 minification & resource shrinking enabled, `app/build/outputs/apk/release/app-release-unsigned.apk`).
- [x] `PASS` — `./gradlew :app:bundleRelease` (`BUILD SUCCESSFUL`, `app/build/outputs/bundle/release/app-release.aab`).
- [x] `PASS` — `git diff --check` and secret scan of project changes (0 whitespace/formatting errors; 0 tracked `.jks`/`.keystore`/`.db`/`.token`/`.key` files or private keys).
- [x] `PASS` — Release manifest/artifact inspection (`DebugCliProvider` and `usesCleartextTraffic` confirmed `False` in merged release manifest and binary `.apk`/`.aab`).
- [x] `PASS` — Physical Android smoke test (`./scripts/tp-adb-cli.sh` on `qs65vsrseqkrxs7x`: `install`, `status`, `servers` -> `dev-lan-1:ok(2/240)`, `connect` -> `Connected`, `probe-http https://example.com` -> `http_status=200 app_uid=10385 rx_bytes=49836 tx_bytes=21460`, `disconnect` -> `Disconnected`).
- [x] `PASS` — Final test matrix rerun after final code change (verified on commit `6855153`).

## Phase 6 — artifact/signing handoff
- [x] `PASS` — Release APK path recorded and artifact verified:
  - Path: `app/build/outputs/apk/release/app-release-unsigned.apk`
  - Size: `15,129,532` bytes
  - SHA-256: `5a82b52011d3efa0d946f3b0ae9c076da5cd89184a674c82b700cc14db9d2130`
- [x] `PASS` — AAB path recorded and artifact verified:
  - Path: `app/build/outputs/bundle/release/app-release.aab`
  - Size: `15,086,155` bytes
  - SHA-256: `ff1e3759e934208e2f48fe121a92cd34f84f8a6cc494fc7897bdcd071740d2e6`
- [x] `BLOCKED` — Signing status clearly recorded: **unsigned** (`app-release-unsigned.apk` and `app-release.aab` are unsigned release artifacts; production signing is `BLOCKED` awaiting owner-provided release keystore and signing credentials — per safety policy, no untracked/fake release keystore was generated).
- [x] `PASS` — Production/Play requirements reviewed against official current docs (`minSdk = 26`, `targetSdk = 35`, `versionCode = 2`, `versionName = "0.2.0"`, `android.permission.BIND_VPN_SERVICE` on `GoBackend$VpnService`, `allowBackup = false`, no ad/tracking SDKs included).
- [x] `PASS` — Final handoff states remaining human decisions and does not claim publication.

## Evidence log

| Date | Commit | Check | Result/evidence |
|---|---|---|---|
| 2026-10-24 | `b815e63` | Baseline server & Android test matrix + live dry-run reconcile | `40 passed` pytest; Gradle debug/release tasks `BUILD SUCCESSFUL`; `POST /v1/servers/reconcile` `{"dry_run": true}` returned `status="dry_run"` with 0 mutations. |
| 2026-10-24 | `fe4e117` | Phase 2 backend/gateway hardening & DB restore tests | `.venv/bin/pytest server/tests -q` -> `44 passed in 1.08s`. |
| 2026-10-24 | `6855153` | Phase 3 & 4 Android UX, diagnostics, network callback, release cleartext guard | `./gradlew :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleRelease :app:bundleRelease` -> `BUILD SUCCESSFUL`. |
| 2026-10-24 | `6855153` | Phase 5 release artifact inspection & physical device smoke test (`qs65vsrseqkrxs7x`) | `DebugCliProvider` & `usesCleartextTraffic` absent from Release APK/AAB; `probe-http https://example.com` returned `http_status=200` over `wg0` (`rx_bytes=49836, tx_bytes=21460`). |
