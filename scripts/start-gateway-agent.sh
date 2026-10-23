#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

TOKEN="$(openssl rand -hex 32)"
printf '%s\n' "$TOKEN" | sudo tee /tmp/tunnelpilot-gateway-agent-token >/dev/null
sudo chmod 600 /tmp/tunnelpilot-gateway-agent-token

echo "Starting Gateway Agent on 127.0.0.1:8787..."
sudo env \
  TUNNELPILOT_GATEWAY_AGENT_TOKEN="$TOKEN" \
  TUNNELPILOT_WG_INTERFACE=tunnelpilot0 \
  TUNNELPILOT_WG_MAX_PEERS=240 \
  "$REPO_ROOT/.venv/bin/uvicorn" \
  server.gateway_agent.app:app --host 127.0.0.1 --port 8787
