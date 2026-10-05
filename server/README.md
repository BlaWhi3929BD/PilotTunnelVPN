# TunnelPilot control plane + gateway agent

The server side now has two deliberately separate services:

- **Control plane**: device registration, address allocation, peer provisioning/revocation orchestration.
- **Gateway agent**: a small privileged process that is allowed to execute WireGuard peer changes on the gateway host.

The control plane never receives a client private key and never needs the gateway private key.

## Control plane API

- `GET /healthz` — liveness.
- `GET /v1/servers` — enabled WireGuard gateways.
- `POST /v1/devices` — registers a client public key, allocates a `/32`, and provisions the peer when a gateway agent is configured.
- `DELETE /v1/devices/{device_id}` — revokes the device and removes its gateway peer.

Registration is still backed by an in-memory store for development. Production needs a durable database and authenticated device identity.

### Environment

```text
TUNNELPILOT_CONTROL_PLANE_TOKEN=optional-control-plane-Bearer-token
TUNNELPILOT_GATEWAY_AGENT_URL=http://127.0.0.1:8787
TUNNELPILOT_GATEWAY_AGENT_TOKEN=long-random-secret
TUNNELPILOT_VPN_ADDRESS_POOL=10.67.0.0/24
TUNNELPILOT_VPN_GATEWAY_ADDRESS=10.67.0.1
```

The gateway agent URL can also be set per server with the `gateway_api_url` field in the server catalog.

## Gateway agent

Run the agent on the WireGuard gateway host where `wg` can access the target interface.

```bash
export TUNNELPILOT_GATEWAY_AGENT_TOKEN='replace-me'
export TUNNELPILOT_WG_INTERFACE=tunnelpilot0
uvicorn server.gateway_agent.app:app --host 127.0.0.1 --port 8787
```

The mutation API is always authenticated. The agent exposes:

- `GET /healthz`
- `POST /v1/peers`
- `DELETE /v1/peers/{public_key}`

The mutation endpoint runs a fixed `wg set ... peer ...` command built from validated public keys and single-address `/32` routes. No shell interpolation is used.

### Important deployment rule

Do not expose the gateway agent directly to the public internet. Keep it on localhost, a private management network, or behind a mutually authenticated proxy. The token is an additional application-level control, not a replacement for network isolation.

## Tests

```bash
pip install -r server/requirements-dev.txt
pytest server/tests -q
```

## Still required before production

- durable database and transactional allocation
- real device authentication / identity binding
- encrypted, short-lived client configuration issuance
- gateway health/capacity scoring
- safe rotation with an explicit old/new key transition
- rate limiting and audit-safe logs
- TLS / mTLS for control-plane-to-gateway traffic
- system service supervision on gateways
