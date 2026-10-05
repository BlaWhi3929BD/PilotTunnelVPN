# Roadmap

## M0 — bootstrap (done)
- Android project with modern AGP 9.1 / built-in Kotlin
- Compose UI
- WireGuard Tunnel Library integration
- VPN permission handling
- local encrypted client-config storage
- application allow-list editing (manual VPN session routing)

## M1 — real single-server VPN
- provision one WireGuard gateway
- establish a real test client configuration
- verify tunnel + DNS + reconnect
- add connection diagnostics

## M2 — control plane
- API service
- device registration
- server catalog
- short-lived config issuance
- gateway health and capacity
- rate limiting and audit-safe logs

## M3 — Auto-VPN
- selected app allow-list
- automatic connect on selected app launch
- disconnect grace period
- background lifecycle handling

## M4 — product
- onboarding
- privacy/disclosure
- analytics that exclude traffic contents
- in-app advertising
- premium option
- server ranking

## M5 — release
- security scan
- abuse/risk review
- privacy policy
- Play VpnService declaration
- internal / closed testing
- production rollout
