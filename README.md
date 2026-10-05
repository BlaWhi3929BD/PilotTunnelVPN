# TunnelPilot

TunnelPilot is an Android-first free WireGuard VPN client. The product goal is a simple VPN that can be free with in-app advertising, while keeping VPN traffic handling separate from advertising and analytics.

## What is implemented

- Native Android VPN flow using WireGuard Android Tunnel Library.
- Encrypted local storage for the client configuration with Android Keystore.
- Full-device routing mode.
- Per-app routing mode using WireGuard's Android `IncludedApplications` support.
- Searchable installed-app selector.
- Live RX/TX counters while connected.
- Configuration validation before storage.
- Explicit reconnect flow when routing rules change.
- Control-plane provisioning that generates the client key locally and receives only server/public routing data.
- CI/build and unit-test foundation.

## Important product decision

"Selected apps" mode means the VPN tunnel stays active while only the selected applications are allowed through the VPN. Android's public VPN API supports an allow-list that is fixed when the VPN connection is established; changing it requires establishing a new VPN connection. This is more reliable and more policy-friendly than trying to monitor which app is foregrounded and repeatedly starting/stopping the VPN.

## Roadmap

### M2 — gateway + control plane
- one production-like WireGuard gateway
- server health endpoint
- device registration using a locally generated client public key
- short-lived client configuration issuance
- peer rotation/revocation
- server catalog and health scoring

### M3 — product polish
- onboarding
- connection diagnostics
- DNS/route validation
- crash reporting and privacy-safe analytics
- quick settings / reconnect affordance
- transparent privacy disclosures

### M4 — monetization
- in-app ads only
- explicit consent flow where required
- optional rewarded ads using an opt-in reward model
- optional premium tier

### M5 — release
- security audit
- VPN declaration and store listing disclosure
- privacy policy / data safety documentation
- closed beta
- production rollout

## Security rules

Never commit WireGuard private keys, server private keys, API tokens, signing keys, ad credentials, or production database secrets.
