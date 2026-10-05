# WireGuard gateway

The gateway is designed around plain WireGuard on Linux rather than a third-party VPN control panel.

## Bootstrap

1. Create a small Ubuntu gateway.
2. Copy `bootstrap-gateway.sh` to it and run as root.
3. Allow UDP `51820` in the cloud firewall/security rules.
4. Generate a client keypair on a trusted admin machine or in the client app.
5. Add only the client **public** key to the gateway using `add-peer.sh`.
6. Keep the client private key on the client. Never store it in Git or send it to chat.

## Current testing mode

The Android M0/M1 client accepts a normal WireGuard client config pasted into the app. This lets us validate the real tunnel before introducing the control plane.

## Production TODO

The eventual control plane must provision peers without exposing the server private key, support rotation/revocation, enforce quotas, and keep sensitive VPN telemetry out of application logs.
