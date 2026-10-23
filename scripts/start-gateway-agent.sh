#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

mkdir -p "$REPO_ROOT/server/data"
chmod 700 "$REPO_ROOT/server/data"
TOKEN_FILE="$REPO_ROOT/server/data/gateway-agent.token"

TOKEN="$(openssl rand -hex 32)"
umask 077
printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
# Keep /tmp path synced for backward compatibility with already-running scripts
printf '%s\n' "$TOKEN" | sudo tee /tmp/tunnelpilot-gateway-agent-token >/dev/null
sudo chmod 600 /tmp/tunnelpilot-gateway-agent-token

TARGET_UID="$(id -u)"
TARGET_GID="$(id -g)"

echo "Starting Gateway Agent on 127.0.0.1:8787 (unprivileged UID=$TARGET_UID with CAP_NET_ADMIN only)..."
exec sudo setpriv \
  --reuid="$TARGET_UID" \
  --regid="$TARGET_GID" \
  --init-groups \
  --inh-caps=-all,+net_admin \
  --ambient-caps=+net_admin \
  env \
  TUNNELPILOT_GATEWAY_AGENT_TOKEN="$TOKEN" \
  TUNNELPILOT_WG_INTERFACE=tunnelpilot0 \
  TUNNELPILOT_WG_MAX_PEERS=240 \
  "$REPO_ROOT/.venv/bin/uvicorn" \
  server.gateway_agent.app:app --host 127.0.0.1 --port 8787
