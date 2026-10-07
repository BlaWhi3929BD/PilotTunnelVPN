# TunnelPilot control plane + gateway agent

The server side now has two deliberately separate services:

- **Control plane**: device registration, persistent address allocation, device authentication, server health selection, and peer provisioning/revocation orchestration.
- **Gateway agent**: a small privileged process that is allowed to execute WireGuard peer changes on the gateway host.

The control plane never receives a client private key and never needs the gateway private key.

## Persistent state

Control-plane device state is stored in SQLite. The default database path is:

```text
server/data/tunnelpilot.db
```

Override it with:

```text
TUNNELPILOT_DATABASE_PATH=/path/to/tunnelpilot.db
```

The database file is ignored by Git. Back it up as part of production server operations.

## Control plane API

- `GET /healthz` — liveness.
- `GET /v1/servers` — enabled WireGuard gateways with live health/capacity information.
- `POST /v1/devices` — creates or re-authenticates a device, allocates a persistent `/32`, selects a healthy gateway, and idempotently provisions its peer.
- `DELETE /v1/devices/{device_id}` — admin-only revocation and peer removal.

The first successful device registration returns an opaque device token. Store it securely and send it as `X-Device-Token` on later registrations. The Android client stores this token encrypted with Android Keystore.

The gateway mutation is retried on every authenticated re-registration, so a control-plane restart does not silently orphan a device whose peer disappeared from the gateway.

### Environment

```text
TUNNELPILOT_CONTROL_PLANE_TOKEN=optional-admin-Bearer-token
TUNNELPILOT_GATEWAY_AGENT_URL=http://127.0.0.1:8787
TUNNELPILOT_GATEWAY_AGENT_TOKEN=long-random-secret
TUNNELPILOT_DATABASE_PATH=server/data/tunnelpilot.db
TUNNELPILOT_VPN_ADDRESS_POOL=10.67.0.0/24
TUNNELPILOT_VPN_GATEWAY_ADDRESS=10.67.0.1
TUNNELPILOT_SERVER_ID=dev-lan-1
TUNNELPILOT_SERVER_REGION=dev-lan
TUNNELPILOT_SERVER_HOSTNAME=192.168.1.85
TUNNELPILOT_SERVER_PUBLIC_KEY=<gateway-public-key>
TUNNELPILOT_SERVER_PORT=51820
```

### Security boundary

`X-Device-Token` authenticates the device to the control plane after initial enrollment. `Authorization: Bearer ...` remains reserved for control-plane administration such as revocation. Use HTTPS in any deployment where these credentials cross an untrusted network.

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
- `DELETE /v1/peers`

The mutation endpoint runs a fixed `wg set ... peer ...` command built from validated public keys and single-address `/32` routes. No shell interpolation is used.

### Important deployment rule

Do not expose the gateway agent directly to the public internet. Keep it on localhost, a private management network, or behind a mutually authenticated proxy. The token is an additional application-level control, not a replacement for network isolation.

## Tests

```bash
pip install -r server/requirements-dev.txt
pytest server/tests -q
```

## Still required before production

- safe peer rotation with an explicit old/new key transition
- durable multi-server inventory rather than environment-only catalog configuration
- rate limiting and audit-safe logs
- TLS / mTLS for control-plane-to-gateway traffic
- system service supervision on gateways
- backup/restore procedure for the control-plane database
