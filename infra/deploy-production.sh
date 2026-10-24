#!/usr/bin/env bash
set -euo pipefail

# TunnelPilot Production Deployment Helper for Linux (Ubuntu, Debian, Fedora, Arch)
# Must be run as root (sudo).

if [[ "${EUID}" -ne 0 ]]; then
  echo "Error: This script must be run as root (sudo)." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="/opt/tunnelpilot"
CONFIG_DIR="/etc/tunnelpilot"
USER="tunnelpilot"
GROUP="tunnelpilot"

echo "=== TunnelPilot Production Deployment ==="

# 1. Create system user and group if not already existing
if ! id "$USER" >/dev/null 2>&1; then
  echo "Creating dedicated system user and group '$USER'..."
  useradd --system --user-group --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$USER"
fi

# 2. Setup directory tree
echo "Setting up installation directories..."
mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/server/data" "$CONFIG_DIR"
chown -R "$USER:$GROUP" "$INSTALL_DIR"
chmod 700 "$CONFIG_DIR"
chmod 700 "$INSTALL_DIR/server/data"

# 3. Setup Python virtual environment
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  echo "Creating Python virtual environment in $INSTALL_DIR/.venv..."
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
fi

echo "Installing server dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install -r "$REPO_ROOT/server/requirements.txt"

# 4. Sync application files
echo "Syncing code to $INSTALL_DIR..."
rsync -a --exclude='.git' --exclude='.gradle' --exclude='build' --exclude='*.db' \
  "$REPO_ROOT/server" "$REPO_ROOT/infra" "$REPO_ROOT/scripts" "$INSTALL_DIR/"
chown -R "$USER:$GROUP" "$INSTALL_DIR"

# 5. Generate secure production tokens if not already present
umask 077
if [[ ! -f "$CONFIG_DIR/gateway.env" ]]; then
  GATEWAY_TOKEN="$(openssl rand -hex 32)"
  cat > "$CONFIG_DIR/gateway.env" <<EOF
TUNNELPILOT_GATEWAY_AGENT_TOKEN=${GATEWAY_TOKEN}
TUNNELPILOT_WG_INTERFACE=tunnelpilot0
TUNNELPILOT_WG_MAX_PEERS=240
EOF
  chown "$USER:$GROUP" "$CONFIG_DIR/gateway.env"
  chmod 600 "$CONFIG_DIR/gateway.env"
fi

if [[ ! -f "$CONFIG_DIR/control-plane.env" ]]; then
  ADMIN_TOKEN="$(openssl rand -hex 32)"
  GATEWAY_TOKEN="$(grep -E '^TUNNELPILOT_GATEWAY_AGENT_TOKEN=' "$CONFIG_DIR/gateway.env" | cut -d= -f2)"
  cat > "$CONFIG_DIR/control-plane.env" <<EOF
TUNNELPILOT_ENVIRONMENT=production
TUNNELPILOT_CONTROL_PLANE_TOKEN=${ADMIN_TOKEN}
TUNNELPILOT_GATEWAY_AGENT_URL=http://127.0.0.1:8787
TUNNELPILOT_GATEWAY_AGENT_TOKEN=${GATEWAY_TOKEN}
TUNNELPILOT_ALLOW_OPEN_REGISTRATION=true
TUNNELPILOT_DATABASE_PATH=${INSTALL_DIR}/server/data/tunnelpilot.db
EOF
  chown "$USER:$GROUP" "$CONFIG_DIR/control-plane.env"
  chmod 600 "$CONFIG_DIR/control-plane.env"
fi

# 6. Install systemd unit files
echo "Installing systemd services and timer..."
cp "$REPO_ROOT/infra/systemd/tunnelpilot-gateway.service" /etc/systemd/system/
cp "$REPO_ROOT/infra/systemd/tunnelpilot-control-plane.service" /etc/systemd/system/
cp "$REPO_ROOT/infra/systemd/tunnelpilot-backup.service" /etc/systemd/system/
cp "$REPO_ROOT/infra/systemd/tunnelpilot-backup.timer" /etc/systemd/system/

systemctl daemon-reload
systemctl enable tunnelpilot-gateway.service
systemctl enable tunnelpilot-control-plane.service
systemctl enable --now tunnelpilot-backup.timer

echo "=== Deployment files installed successfully ==="
echo "To start services:"
echo "  sudo systemctl restart tunnelpilot-gateway.service"
echo "  sudo systemctl restart tunnelpilot-control-plane.service"
