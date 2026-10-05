# TunnelPilot architecture

## Product

TunnelPilot is a free Android VPN client with an eventual optional premium tier. The core experience is a real VPN connection; advertising must remain inside the TunnelPilot app and must never be used as a reason to manipulate or monetize traffic from other applications.

## Components

```text
Android app
  ├── UI (Jetpack Compose)
  ├── VPN permission / lifecycle
  ├── WireGuard Android Tunnel Library
  ├── Server selector
  ├── Auto-VPN policy
  └── Ads / analytics (later)
          │
          ▼
Control plane API
  ├── Device registration
  ├── Short-lived client configuration issuance
  ├── Server catalog
  └── Health / capacity data
          │
          ▼
WireGuard gateways
```

## Security principles

1. Never embed a long-lived private WireGuard key in the APK.
2. Client configuration must be issued by the control plane and scoped to the device/account.
3. The VPN tunnel must be encrypted end-to-end to the gateway.
4. Ads are an app UX concern; they must not influence routing decisions.
5. No traffic logging by default.
6. Security scanning is required before release.
7. Store policy requirements are part of the architecture, not a release-afterthought.

## Current milestone

M0 creates the Android project, Compose shell, WireGuard library integration, permission flow, and fail-closed connection path. It intentionally does **not** connect to an invented or hard-coded server.

## Next milestone

Build the control plane and provision the first WireGuard gateway. Then issue a test configuration to the Android client and implement a real connect/disconnect path.
