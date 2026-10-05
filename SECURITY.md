# Security policy

## Secrets

Do not commit:

- WireGuard private keys
- API tokens
- cloud credentials
- signing keys
- ad network private credentials
- database passwords

Use environment variables / secret managers and short-lived credentials wherever possible.

## Threat model priorities

- VPN credential theft
- malicious or substituted server configuration
- MITM against the control plane
- accidental traffic leakage
- DNS leakage
- key reuse across devices
- insecure logging
- ad SDK abuse
- supply-chain vulnerabilities

Security scans are a release gate for production builds.
