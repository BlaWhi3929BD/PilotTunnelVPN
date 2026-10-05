# TunnelPilot control plane (development skeleton)

This service is intentionally small. It defines the API boundary for future device registration and server discovery.

It is **not production-ready** and does not provision peers yet.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

## Production work still required

- PostgreSQL or another managed database
- real authentication / device identity
- public-key-only device registration
- gateway agent or secure orchestration for peer creation
- short-lived configuration issuance
- key rotation and revocation
- rate limiting
- audit-safe logging
- server health and capacity data
- TLS and secret management
