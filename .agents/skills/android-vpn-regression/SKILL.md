---
name: android-vpn-regression
description: Procedures for verifying Android WireGuard VPN connectivity, routing modes (All Apps vs Selected Apps), and Keystore security.
---

# Android VPN Regression Guide

## Routing Modes
- **All Apps (`ALL_APPS`)**: `AllowedIPs = 0.0.0.0/0`. All device traffic traverses the tunnel.
- **Selected Apps (`SELECTED_APPS`)**: Uses `IncludedApplications` directive in WireGuard config. Only selected packages traverse the tunnel; non-selected traffic routes directly. Reconnection is required when app list changes.

## Verification Steps
1. Verify tunnel configuration stored encrypted with Android Keystore.
2. Check `VpnService.prepare` flow.
3. Validate RX/TX byte counters increase on both client and gateway interface (`tunnelpilot0`).
