---
name: security-review
description: Threat model checklist, secret handling, subprocess safety, and boundary validation for TunnelPilot.
---

# Security Review Guidelines

## Sensitive Boundaries
- Never commit WireGuard private keys, `.env`, tokens, signing keys, or SQLite databases.
- Gateway Agent must run isolated and accept only strict base64 32-byte public keys and /32 IPv4 addresses.
- External commands must use fixed argument arrays without shell interpolation.
- Timing-safe comparisons (`hmac.compare_digest`) must be used for token verification.
