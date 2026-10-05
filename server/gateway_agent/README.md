# TunnelPilot gateway agent

This service runs **on the WireGuard gateway host** and is the only component in this milestone that is allowed to call `wg set`.

## Run locally on the gateway

```bash
cd /path/to/PilotTunnelVPN
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements-dev.txt
export TUNNELPILOT_GATEWAY_AGENT_TOKEN="$(openssl rand -hex 32)"
export TUNNELPILOT_WG_INTERFACE=tunnelpilot0
uvicorn server.gateway_agent.app:app --host 127.0.0.1 --port 8787
```

The default interface matches the development gateway created by `infra/wireguard/dev-lan-gateway.sh`.

## API

Health:

```bash
curl http://127.0.0.1:8787/healthz
```

Provision a peer:

```bash
curl -X POST http://127.0.0.1:8787/v1/peers \
  -H "Authorization: Bearer $TUNNELPILOT_GATEWAY_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"public_key":"<CLIENT_PUBLIC_KEY>","allowed_ip":"10.67.0.2/32"}'
```

Revoke a peer:

```bash
curl -X DELETE "http://127.0.0.1:8787/v1/peers?public_key=<CLIENT_PUBLIC_KEY>" \
  -H "Authorization: Bearer $TUNNELPILOT_GATEWAY_AGENT_TOKEN"
```

## Security boundary

The agent accepts a WireGuard **public key and single client address only**. It never receives a client private key or the gateway private key through the API.

Do not bind the agent to `0.0.0.0` on an internet-facing host. Use localhost, a private management network, or a mutually authenticated reverse proxy. Rotate the agent token before any real deployment.
