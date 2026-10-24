#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

mkdir -p "$REPO_ROOT/server/data"
chmod 700 "$REPO_ROOT/server/data"
TOKEN_FILE="$REPO_ROOT/server/data/gateway-agent.token"

umask 077
if [[ -n "${TUNNELPILOT_GATEWAY_AGENT_TOKEN:-}" ]]; then
  TOKEN="$TUNNELPILOT_GATEWAY_AGENT_TOKEN"
  printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
elif [[ -s "$TOKEN_FILE" ]] && [[ "${TUNNELPILOT_ROTATE_GATEWAY_TOKEN:-0}" != "1" ]] && [[ "${TUNNELPILOT_ROTATE_GATEWAY_TOKEN:-false}" != "true" ]]; then
  TOKEN="$(cat "$TOKEN_FILE")"
else
  TOKEN="$(openssl rand -hex 32)"
  printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
fi
chmod 600 "$TOKEN_FILE"
if sudo test -f /etc/wireguard/tunnelpilot0-server_public.key; then
  sudo cat /etc/wireguard/tunnelpilot0-server_public.key > "$REPO_ROOT/server/data/gateway-public.key"
  chmod 600 "$REPO_ROOT/server/data/gateway-public.key"
fi

TARGET_UID="$(id -u)"
TARGET_GID="$(id -g)"

WG_IFACE="${TUNNELPILOT_WG_INTERFACE:-tunnelpilot0}"
WG_MAX="${TUNNELPILOT_WG_MAX_PEERS:-240}"

echo "Starting Gateway Agent on 127.0.0.1:8787 (unprivileged UID=$TARGET_UID with CAP_NET_ADMIN only)..."
exec sudo setpriv \
  --reuid="$TARGET_UID" \
  --regid="$TARGET_GID" \
  --init-groups \
  --inh-caps=-all,+net_admin \
  --ambient-caps=+net_admin \
  env \
  TUNNELPILOT_GATEWAY_AGENT_TOKEN="$TOKEN" \
  TUNNELPILOT_WG_INTERFACE="$WG_IFACE" \
  TUNNELPILOT_WG_MAX_PEERS="$WG_MAX" \
  "$REPO_ROOT/.venv/bin/uvicorn" \
  server.gateway_agent.app:app --host 127.0.0.1 --port 8787
