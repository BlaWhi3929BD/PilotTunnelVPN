#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

TOKEN_FILE="$REPO_ROOT/server/data/gateway-agent.token"
if [[ -f "$TOKEN_FILE" ]]; then
  GATEWAY_TOKEN="$(cat "$TOKEN_FILE")"
elif [[ -f /tmp/tunnelpilot-gateway-agent-token ]]; then
  GATEWAY_TOKEN="$(sudo cat /tmp/tunnelpilot-gateway-agent-token)"
else
  echo "Error: gateway agent token not found. Start gateway agent first!" >&2
  exit 1
fi
SERVER_PUBKEY="$(sudo cat /etc/wireguard/tunnelpilot0-server_public.key)"

# Detect USB tethering interface IP if present, otherwise default route IP
ENDPOINT_IP="$(ip -4 addr show enp0s20f0u4 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 || true)"
if [[ -z "$ENDPOINT_IP" ]]; then
  ENDPOINT_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
fi

echo "Control Plane Host Endpoint for WireGuard: $ENDPOINT_IP"

export TUNNELPILOT_GATEWAY_AGENT_URL="http://127.0.0.1:8787"
export TUNNELPILOT_GATEWAY_AGENT_TOKEN="$GATEWAY_TOKEN"
export TUNNELPILOT_SERVER_ID="dev-lan-1"
export TUNNELPILOT_SERVER_REGION="dev-lan"
export TUNNELPILOT_SERVER_HOSTNAME="$ENDPOINT_IP"
export TUNNELPILOT_SERVER_PORT="51820"
export TUNNELPILOT_SERVER_PUBLIC_KEY="$SERVER_PUBKEY"
export TUNNELPILOT_VPN_ADDRESS_POOL="10.67.0.0/24"
export TUNNELPILOT_VPN_GATEWAY_ADDRESS="10.67.0.1"
export TUNNELPILOT_DATABASE_PATH="$REPO_ROOT/server/data/tunnelpilot.db"

exec "$REPO_ROOT/.venv/bin/uvicorn" server.app.main:app --host 0.0.0.0 --port 8000
