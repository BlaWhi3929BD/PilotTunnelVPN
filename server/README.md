# TunnelPilot control plane (development skeleton)

This service defines the API boundary for server discovery and device registration.

Current development behavior:

- `GET /healthz` exposes a basic liveness check.
- `GET /v1/servers` returns enabled WireGuard gateways.
- `POST /v1/devices` validates and registers a client **public key only**, then assigns the first enabled server.
- Registration state is kept in memory and is intentionally lost on restart.
- Peer provisioning and client configuration issuance are still disabled.

It is **not production-ready**.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements-dev.txt
uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

For development, `TUNNELPILOT_CONTROL_PLANE_TOKEN` can be set to require a Bearer token for device registration.

## Production work still required

- PostgreSQL or another managed database
- real device authentication / identity binding
- gateway agent or secure orchestration for peer creation
- short-lived configuration issuance
- key rotation and revocation
- rate limiting
- audit-safe logging
- real server health and capacity data
- TLS and secret management
