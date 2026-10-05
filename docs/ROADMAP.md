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

## M2 — real gateway
- deploy one WireGuard gateway
- verify DNS/IPv4/IPv6 behavior
- verify reconnect and sleep/wake
- verify per-app routing on a physical device
- gateway health endpoint

## M3 — control plane
- device registration by public key
- peer provisioning
- configuration rotation/revocation
- server catalog
- capacity/health scoring

## M4 — monetization
- privacy/consent UX
- in-app ads
- optional rewarded ads
- optional premium

## M5 — release
- security review
- abuse/risk review
- Play VpnService declaration
- privacy policy
- Data safety disclosure
- internal and closed testing
- production rollout
