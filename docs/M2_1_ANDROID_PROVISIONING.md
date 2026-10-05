# M2.1 Android provisioning

TunnelPilot can now bootstrap a WireGuard configuration from the control plane without asking the user to paste a WireGuard config manually.

## Flow

```text
Android
  ├─ generate client private key locally
  ├─ derive client public key locally
  ├─ register device_id + public key
  ▼
Control plane
  ├─ allocates a client /32
  ├─ asks the gateway agent to add the public key
  └─ returns gateway hostname/public key/port + client address
  ▼
Android
  ├─ builds the WireGuard config locally
  ├─ stores the full config encrypted with Android Keystore
  └─ connects using the existing WireGuard backend
```

The control plane never receives the client private key.

## Development setup

Run the control plane so Android can reach it over the LAN:

```fish
unset TUNNELPILOT_CONTROL_PLANE_TOKEN
export TUNNELPILOT_GATEWAY_AGENT_TOKEN="..."
export TUNNELPILOT_GATEWAY_AGENT_URL="http://127.0.0.1:8787"
uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

Configure `SERVERS[0]` in `server/app/main.py` with the real development gateway hostname and WireGuard server public key, or replace the development catalog with environment-backed configuration before testing on a physical phone.

For a physical Android device on the same LAN, set the Setup tab's control plane URL to the Linux host's LAN address, for example `http://192.168.1.85:8000`.

The debug Android manifest permits cleartext HTTP for local development only. The release manifest does not opt into cleartext traffic.
