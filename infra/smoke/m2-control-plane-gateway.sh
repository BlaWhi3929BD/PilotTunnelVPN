#!/usr/bin/env bash
set -euo pipefail

# Verifies the M2 control-plane -> gateway-agent provisioning path.
# It does not require or handle an Android private key.
#
# Required:
#   CONTROL_PLANE_URL
#   DEVICE_ID
#   CLIENT_PUBLIC_KEY
#
# Optional:
#   CONTROL_PLANE_TOKEN
#   APP_VERSION (default 0.2.0)
#   CLEANUP=1 to revoke the test device after a successful registration

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
DEVICE_ID="${DEVICE_ID:?Set DEVICE_ID to a stable test identifier}"
CLIENT_PUBLIC_KEY="${CLIENT_PUBLIC_KEY:?Set CLIENT_PUBLIC_KEY to a WireGuard public key}"
APP_VERSION="${APP_VERSION:-0.2.0}"
CLEANUP="${CLEANUP:-0}"

curl_args=(--fail --silent --show-error)
if [[ -n "${CONTROL_PLANE_TOKEN:-}" ]]; then
  curl_args+=(-H "Authorization: Bearer ${CONTROL_PLANE_TOKEN}")
fi

json_value() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
value = payload
for part in sys.argv[2].split('.'):
    if isinstance(value, list):
        value = value[int(part)]
    else:
        value = value[part]
print(value)
PY
}

echo "[1/4] control plane health"
curl "${curl_args[@]}" "${CONTROL_PLANE_URL}/healthz" >/dev/null

echo "[2/4] gateway health through server catalog"
servers_json="$(curl "${curl_args[@]}" "${CONTROL_PLANE_URL}/v1/servers")"
server_status="$(json_value "${servers_json}" '0.health_status')"
[[ "${server_status}" == "ok" || "${server_status}" == "full" ]] || {
  echo "Gateway is not healthy: ${server_status}" >&2
  exit 1
}

printf 'Gateway status: %s\n' "${server_status}"

payload="$(python3 - <<PY
import json
print(json.dumps({
    "device_id": "${DEVICE_ID}",
    "client_public_key": "${CLIENT_PUBLIC_KEY}",
    "app_version": "${APP_VERSION}",
}))
PY
)"

echo "[3/4] device registration + peer provisioning"
registration="$(curl "${curl_args[@]}" \
  -H 'Content-Type: application/json' \
  -X POST \
  -d "${payload}" \
  "${CONTROL_PLANE_URL}/v1/devices")"

provisioned="$(json_value "${registration}" 'provisioned')"
client_address="$(json_value "${registration}" 'client_address')"
server_hostname="$(json_value "${registration}" 'server.hostname')"
server_public_key="$(json_value "${registration}" 'server.public_key')"

[[ "${provisioned}" == "True" ]] || {
  echo "Registration succeeded but peer was not provisioned: ${registration}" >&2
  exit 1
}

printf 'Provisioned: %s\n' "${provisioned}"
printf 'Client address: %s\n' "${client_address}"
printf 'Gateway endpoint: %s\n' "${server_hostname}"
printf 'Gateway public key: %s\n' "${server_public_key}"

echo "[4/4] done"
echo "Now connect the Android client and verify a fresh WireGuard handshake on the gateway."

if [[ "${CLEANUP}" == "1" ]]; then
  echo "Revoking test device"
  curl "${curl_args[@]}" -X DELETE "${CONTROL_PLANE_URL}/v1/devices/${DEVICE_ID}" >/dev/null
fi
