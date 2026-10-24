# TunnelPilot — Privacy Policy & Zero-Log Declaration

*Last updated: October 24, 2026*

TunnelPilot ("we", "our", or "the App") is committed to protecting your privacy. This document outlines our strict **Zero-Log policy**, explains how your data is handled, and details how our service complies with Google Play policies and international data protection laws (including GDPR and CCPA).

---

## 1. Core Principle: Zero-Log VPN Network

When you connect to the VPN using TunnelPilot, an encrypted tunnel is established between your device and a remote WireGuard gateway.

**We do NOT:**
- Log, monitor, store, or inspect the websites, IP addresses, or services you visit.
- Log or record DNS queries made through the tunnel.
- Log, inspect, or intercept the content of communications traversing the tunnel.
- Sell, rent, monetize, or trade any network traffic data to third parties.

**Technical Enforcement:**
- WireGuard operates entirely at Layer 3 using state-of-the-art cryptography (ChaCha20-Poly1305, Curve25519, BLAKE2s).
- Packets are forwarded statelessly by the gateway using the Linux kernel WireGuard module and ephemeral network address translation (NAT). No session connection histories or packet payloads are recorded to disk.

---

## 2. Cryptographic Keys & Local Security

- **Private Key Isolation:** Your WireGuard private key is generated locally on your Android device and stored inside the **Android Keystore** hardware-backed security module (`AES/GCM/NoPadding`).
- **Zero Server Knowledge:** Your private key is **never** transmitted across the network, never sent to the Control Plane, and never stored on any server.
- **Public Key Registration:** The backend server receives only your WireGuard public key (which is mathematically impossible to reverse into a private key) to allow the gateway interface to recognize incoming encrypted handshakes.

---

## 3. Account & Device Data

TunnelPilot is designed to operate without requiring usernames, passwords, email addresses, or phone numbers.

- **Device Identifier (`device_id`):** Upon first setup, the app generates a random UUID (e.g., `aea6670d-c4f8-48db-8bd3-8dd246998d3d`) stored in private app storage. This identifier is used exclusively to maintain your tunnel configuration and server pinning.
- **Device Authentication Token:** An ephemeral cryptographic token issued by the Control Plane to authenticate requests such as server migrations and key rotations. The backend stores only an irreversible SHA-256 hash of this token.
- **Assigned IP Address:** A private subnet IP address (e.g., `10.67.0.2/32`) allocated to your device while active on a server.
- **Revocation & Deletion:** You can delete your identity and configuration at any time directly in the app (**Setup > Reset Device Identity**). This deletes your device record from both SQLite storage and WireGuard gateway routing tables.

---

## 4. Advertising & Monetization (Strict Policy Compliance)

TunnelPilot offers a free tier supported by in-app sponsor placements.

**Strict Google Play VpnService Compliance:**
In accordance with Google Play's [VpnService Policy](https://support.google.com/googleplay/android-developer/answer/12564964):
1. **Network Isolation:** Advertising SDKs and sponsor placements are strictly confined to the application's user interface. They have **zero access** to the VPN tunnel socket, `VpnService.Builder` network routing, or traffic from other applications on your device.
2. **No Traffic Manipulation:** TunnelPilot never redirects, modifies, injects, or proxies traffic from other applications for ad monetization.
3. **Consent Choice (GDPR / UMP):** Before any advertising is presented, users are prompted with a clear consent choice between personalized recommendations and basic non-personalized sponsors. This choice can be reviewed or changed at any time in **Setup > Privacy & Advertising Choice**.
4. **Ad-Free Option:** Users holding a Premium tier or who unlock temporary ad-free access (e.g., through voluntary rewarded sponsor interactions) experience zero ads throughout the app.

---

## 5. Google Play Data Safety Summary

| Data Category | Data Collected | Purpose | Shared with 3rd Parties? |
|---|---|---|---|
| **App Activity** | None | N/A | No |
| **Web Browsing** | **None (Zero Logs)** | N/A | **No** |
| **User Identifiers** | Random anonymous device UUID | Service operation & server pinning | No |
| **Diagnostics** | Aggregate anonymous crash metrics (if opted in) | App stability | No |
| **Financial / Payment** | Handled securely by Google Play Billing (if purchasing Premium) | In-app purchase processing | Handled by Google Play |

---

## 6. Contact & Updates

For privacy questions or data deletion inquiries regarding TunnelPilot, please open an issue in the official repository or contact the project maintainers.
