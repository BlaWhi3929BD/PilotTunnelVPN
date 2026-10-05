# TunnelPilot

Android-first free VPN project.

> Codename and package name are provisional. The final product name, legal entity, domain, and store listing will be decided before publication.

## Current status

**Milestone 0 — project bootstrap**

- Kotlin + Android Gradle Plugin 9.1.1
- Java 17
- Jetpack Compose
- WireGuard Android Tunnel Library 1.0.23
- VPN permission request flow
- Fail-closed connection path until a real control-plane configuration is available
- Initial unit test
- Security/architecture notes

## Build

Open this directory in current Android Studio and let it provision the matching Gradle distribution. The project is configured for AGP 9.1.1 / Gradle 9.3.1.

A real server configuration is deliberately not included. Never commit WireGuard private keys, tokens, or production server credentials.

## Roadmap

1. Control plane API + database
2. First WireGuard gateway
3. Device registration + short-lived client config issuance
4. Real connect/disconnect
5. Server selection and health scoring
6. Per-app VPN / Auto-VPN
7. In-app advertising without traffic monetization tricks
8. Privacy and consent flows
9. Security audit
10. Closed beta
11. Google Play publication
