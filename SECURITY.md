# Security policy

## Threat model

Priority threats are:

- theft of client or gateway WireGuard private keys
- malicious or substituted server configuration
- man-in-the-middle against the control plane
- accidental traffic leakage
- DNS leakage
- key reuse across devices
- sensitive data in logs or analytics
- malicious ad SDK behavior
- dependency and supply-chain compromise

## Invariants

1. The Android client stores its WireGuard client configuration encrypted with Android Keystore.
2. The production control plane must never receive or store a client private key.
3. Gateway private keys stay on gateways and are never committed to the repository.
4. Advertising and analytics must never alter VPN routing or proxy user traffic for monetization.
5. Sensitive VPN traffic contents are not logged.
6. Security scanning is required before release.

## Reporting

Please do not open a public issue with credentials, private keys, or exploit details. Use a private security channel once the production project establishes one.
