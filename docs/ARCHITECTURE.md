# TunnelPilot architecture

```text
Android client
  ├─ Compose UI
  ├─ Settings / app selection
  ├─ Encrypted WireGuard config store
  ├─ WireGuard Android Tunnel Library
  └─ diagnostics / connection state
          │
          ▼
Control plane API
  ├─ device registration
  ├─ server catalog
  ├─ short-lived config issuance
  ├─ rate limiting
  └─ peer rotation/revocation
          │
          ▼
WireGuard gateways
```

## Routing model

The client supports:

- `ALL_APPS`: normal full-tunnel WireGuard behavior.
- `SELECTED_APPS`: WireGuard's Android allow-list; only listed packages use the tunnel.

The list is established before the tunnel starts. Updating it requires a reconnect.

## Why we do not implement foreground-app surveillance

A generic Android app should not rely on invasive foreground-app monitoring or accessibility abuse just to simulate an "auto VPN" toggle. The platform already provides a first-class per-app VPN model. TunnelPilot uses that model and can later add quick reconnect affordances without watching arbitrary app content.

## Secrets

Client private keys are device-side secrets. The control plane gets public keys only. Gateway private keys remain on gateways.
