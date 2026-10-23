# TunnelPilot control plane + gateway agent

The server side has two deliberately separate services:

- **Control plane**: persistent device registration, address allocation, device authentication, server selection, peer provisioning/revocation, and authenticated WireGuard key rotation.
- **Gateway agent**: a small privileged process that is allowed to execute WireGuard peer changes on the gateway host.

The control plane never receives a client private key and never needs the gateway private key. Device state is persisted in SQLite for this development milestone.

## Control plane API

- `GET /healthz` — liveness.
- `GET /v1/servers` — enabled WireGuard gateways with live health/capacity data.
- `POST /v1/servers/reconcile` & `POST /v1/servers/{server_id}/reconcile` — reconciles SQLite-provisioned device peers with the live WireGuard interface on the gateway (restoring missing peers and removing orphaned peers). Also runs best-effort on Control Plane startup.
- `POST /v1/devices` — first registration allocates a `/32`, issues a device token, and provisions the gateway peer. Existing devices must authenticate with `X-Device-Token`; registration is idempotent and repairs a missing gateway peer.
- `POST /v1/devices/{device_id}/rotate` — authenticated WireGuard public-key rotation while preserving the device ID, VPN address, server assignment, and device token.
- `DELETE /v1/devices/{device_id}` — fail-closed revocation requiring either the admin `Authorization: Bearer <token>` or the device's `X-Device-Token`; removes the gateway peer first and retains the SQLite record on gateway failure unless `?force=true` is specified.

### Environment

```text
TUNNELPILOT_CONTROL_PLANE_TOKEN=optional-admin-Bearer-token
TUNNELPILOT_GATEWAY_AGENT_URL=http://127.0.0.1:8787
TUNNELPILOT_GATEWAY_AGENT_TOKEN=long-random-secret
TUNNELPILOT_DATABASE_PATH=server/data/tunnelpilot.db
TUNNELPILOT_VPN_ADDRESS_POOL=10.67.0.0/24
TUNNELPILOT_VPN_GATEWAY_ADDRESS=10.67.0.1
```

The gateway agent URL can also be set per server with the `gateway_api_url` field in the server catalog.

## Device authentication

On first registration the control plane returns a random device token once. The Android client stores it encrypted with Android Keystore and sends it as `X-Device-Token` for subsequent provisioning and key rotation. The control plane stores only a SHA-256 hash of the token.

## Gateway agent

Run the agent on the WireGuard gateway host where `wg` can access the target interface.

```bash
export TUNNELPILOT_GATEWAY_AGENT_TOKEN='replace-me'
export TUNNELPILOT_WG_INTERFACE=tunnelpilot0
export TUNNELPILOT_WG_MAX_PEERS=240
uvicorn server.gateway_agent.app:app --host 127.0.0.1 --port 8787
```

The mutation API is always authenticated. The agent exposes:

- `GET /healthz`
- `GET /v1/peers`
- `POST /v1/peers`
- `DELETE /v1/peers`

The mutation endpoint runs a fixed `wg set ... peer ...` command built from validated public keys and single-address `/32` routes. No shell interpolation is used.

### Important deployment rule

Do not expose the gateway agent directly to the public internet. Keep it on localhost, a private management network, or behind a mutually authenticated proxy. The token is an additional application-level control, not a replacement for network isolation.

## Development helper scripts

For local development and testing:
- `./scripts/start-gateway-agent.sh`: generates a temporary gateway token and starts the Gateway Agent on `127.0.0.1:8787`.
- `./scripts/start-control-plane.sh`: reads the gateway token and server public key, detects the gateway endpoint IP, and starts the Control Plane on `0.0.0.0:8000`.
- `./scripts/fix-gateway-forwarding.sh`: configures `sysctl` IP forwarding, NAT `MASQUERADE`, and TCP MSS clamping (`--clamp-mss-to-pmtu`) to prevent packet drops on HTTPS traffic.
- `./scripts/tp-adb-cli.sh`: remote CLI wrapper over ADB (`status`, `servers`, `provision`, `rotate-key`, `connect`, `disconnect`, `set-mode`, `set-apps`, `apply-routing`, `revoke`, `reset-identity`) for automated testing of debug builds on a connected Android device.

## Tests

```bash
pip install -r server/requirements-dev.txt
pytest server/tests -q
```

## Still required before production

- transactional multi-server allocation and durable deployment database
- real device identity binding / attestation where appropriate
- short-lived or rotatable device credentials
- gateway health/capacity scoring improvements
- rate limiting and audit-safe logs
- TLS / mTLS for control-plane-to-gateway traffic
- system service supervision on gateways
