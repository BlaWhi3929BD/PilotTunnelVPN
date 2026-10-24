# Google Play Console — Submission & Compliance Guide

This guide provides exact answers and form disclosures required when submitting TunnelPilot to the Google Play Console, specifically addressing the **VpnService policy**, **Data Safety section**, and **Content Rating**.

---

## 1. VpnService Policy Declaration

Google Play requires all applications that declare `android.permission.BIND_VPN_SERVICE` to complete the VpnService declaration form.

### Question: Is the primary functionality of your app a VPN?
- **Answer:** **Yes**.
- **Justification Text (Copy & Paste into Play Console):**
  > "TunnelPilot is a dedicated personal VPN client powered by the modern WireGuard protocol. The app's primary and core purpose is to provide end-to-end encrypted network connectivity between the user's Android device and remote WireGuard servers. The Android VpnService API is used strictly to create the tun network interface, encrypt outgoing IP traffic using WireGuard (Curve25519/ChaCha20-Poly1305), and implement user-configured routing modes (full device protection or per-app split tunneling via VpnService.Builder.addAllowedApplication). TunnelPilot enforces a strict Zero-Log policy, does not inspect or monetize tunnel traffic, and isolates all in-app advertising strictly to the application user interface without modifying or redirecting other apps' network traffic."

### Core Functionality Video Demonstration:
Google Play requires a short YouTube video (can be unlisted) demonstrating the VPN service:
1. Show opening the app and the prominent disclosure dialog explaining VPN use.
2. Show tapping "Connect" and the standard Android system dialog requesting VPN permission.
3. Show the key icon appearing in the status bar and live traffic counters (RX/TX) incrementing.
4. Show navigating to "Apps" and selecting specific apps for split tunneling (Selected Apps mode).
5. Show disconnecting the VPN.

---

## 2. Data Safety Section Responses

In the **App Content > Data Safety** questionnaire in Google Play Console, use the following exact responses:

### 1. Does your app collect or share any of the required user data types?
- **Answer:** **No** (TunnelPilot does not collect personal data, emails, names, contacts, or browsing history).
- If using Google AdMob SDK for in-app banners:
  - Select **Device or other IDs** > **Device or other IDs** (Collected: Yes, Shared: Yes for Advertising, Ephemeral: No, Optional: Yes based on consent).

### 2. Is all of the user data collected by your app encrypted in transit?
- **Answer:** **Yes**.
- All Control Plane communications use TLS/HTTPS, and all VPN traffic is encrypted with WireGuard.

### 3. Do you provide a way for users to request that their data be deleted?
- **Answer:** **Yes**.
- Users can delete their device registration and cryptographic identity instantly via **Setup > Reset Device Identity**.

### 4. Zero-Log Specific Confirmation:
- **Web Browsing History:** NOT collected.
- **Location:** NOT collected.
- **Financial Information:** Handled entirely by Google Play Billing; NOT collected by the app.
- **Messages / Photos / Audio:** NOT collected.

---

## 3. App Access & Ads Questionnaire

- **App Access:** "All functionality is available without special access restrictions" (or provide demo credentials if a private server is used for testing).
- **Contains Ads:** **Yes** ("Yes, my app contains ads" — required because the free tier includes in-app sponsor placements).
- **Target Audience:** Select **18 and older** (or 13+ depending on your target; 18+ avoids COPPA requirements and simplifies ad compliance).
- **Financial Features:** "My app doesn't provide any financial features".
- **Government Apps:** "No".

---

## 4. Privacy Policy URL

Under **App Content > Privacy Policy**, provide the public URL where `docs/PRIVACY_POLICY.md` is hosted (for example, on GitHub Pages: `https://<username>.github.io/PilotTunnelVPN/PRIVACY_POLICY` or on your custom domain).
