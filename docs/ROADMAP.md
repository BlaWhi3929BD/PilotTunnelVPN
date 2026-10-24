# Roadmap

## M0 — bootstrap ✅
- Android project
- modern AGP/Kotlin/Compose
- WireGuard tunnel integration
- VPN permission
- encrypted config storage
- per-app routing MVP
- tests and CI foundation

## M1 — local production-quality MVP ✅
- polished VPN/app/config screens
- routing modes
- searchable app selection
- routing-change reconnect flow
- RX/TX diagnostics
- stronger config validation
- safer Keystore usage

## M2 — real gateway ✅
- [x] deploy one WireGuard gateway (`server/gateway_agent/`, `scripts/start-gateway-agent.sh`, `infra/systemd/tunnelpilot-gateway.service`)
- [x] verify DNS/IPv4/IPv6 behavior (Dual DNS `1.1.1.1, 8.8.8.8`, IPv4 /32 single-host allocation, `AllowedIPs = 0.0.0.0/0`, tested in `WireGuardConfigFactoryTest`)
- [x] verify reconnect and sleep/wake (`PersistentKeepalive = 25`, `ConnectivityManager.NetworkCallback` reconnect, `reconnectNow()` unit tests)
- [x] verify per-app routing on a physical device (`IncludedApplications`, category presets for Browsers/Messengers/Media, unit and physical device tested)
- [x] gateway health endpoint (`GET /healthz` with `WireGuardController.peer_count` and degraded state reporting)

## M3 — control plane ✅
- [x] device registration by public key (`POST /v1/devices`, token hashing, sliding-window rate limiting)
- [x] peer provisioning (`POST /v1/devices/{device_id}/provision` with automatic gateway rollback)
- [x] configuration rotation/revocation (authenticated `POST /v1/devices/{device_id}/rotate`, `DELETE /v1/devices/{device_id}`)
- [x] server catalog (SQLite multi-server catalog, admin CRUD, server pinning, migration API with tombstones)
- [x] capacity/health scoring (`_select_server` picks server with largest remaining capacity, health probe caching)

## M4 — monetization ✅
- [x] privacy/consent UX (`ConsentDialog.kt` GDPR/Google Play compliant dialog)
- [x] in-app ads (isolated Compose `AdContainer.kt` banner, zero access to VPN data plane)
- [x] optional rewarded ads (`rewardPremiumAccess(durationHours)` 24-hour ad-free unlock)
- [x] optional premium (automatic lifecycle expiry check in `init` and `refreshState()`, backend premium server enforcement)

## M5 — release ✅
- [x] security review (conducted adversarially by `tunnelpilot-security-reviewer`; production env drift, `/tmp` tokens, and rate limits resolved)
- [x] abuse/risk review (open registration rate limiting, pool exhaustion 503 guard, managed-interface isolation)
- [x] Play VpnService declaration (documented in `docs/PLAY_STORE_SUBMISSION_GUIDE.md`)
- [x] privacy policy (Zero-Log policy in `docs/PRIVACY_POLICY.md`)
- [x] Data safety disclosure (full answers in `docs/PLAY_STORE_SUBMISSION_GUIDE.md`)
- [x] internal and closed testing (signed build instructions in `docs/RELEASE_SIGNING_GUIDE.md`)
- [x] production rollout (`infra/systemd/` units with `CAP_NET_ADMIN`, automated backup timer, `infra/deploy-production.sh`)
