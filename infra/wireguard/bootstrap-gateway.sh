#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 24.04+ WireGuard gateway bootstrap.
# Run as root on a fresh gateway. No client private keys are generated here.

WG_IFACE="${WG_IFACE:-wg0}"
WG_SUBNET="${WG_SUBNET:-10.66.0.0/24}"
WG_SERVER_ADDRESS="${WG_SERVER_ADDRESS:-10.66.0.1/24}"
WG_PORT="${WG_PORT:-51820}"
WAN_IFACE="${WAN_IFACE:-$(ip route show default | awk '{print $5; exit}')}"

apt-get update
apt-get install -y wireguard iptables

install -d -m 700 /etc/wireguard
umask 077

if [[ ! -f /etc/wireguard/server_private.key ]]; then
  wg genkey | tee /etc/wireguard/server_private.key >/dev/null
fi
wg pubkey < /etc/wireguard/server_private.key > /etc/wireguard/server_public.key

cat > /etc/sysctl.d/99-tunnelpilot.conf <<SYSCTL
net.ipv4.ip_forward=1
SYSCTL
sysctl --system >/dev/null

SERVER_PRIVATE_KEY="$(cat /etc/wireguard/server_private.key)"

cat > "/etc/wireguard/${WG_IFACE}.conf" <<WGCONF
[Interface]
Address = ${WG_SERVER_ADDRESS}
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIVATE_KEY}
SaveConfig = false
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -s ${WG_SUBNET} -o ${WAN_IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s ${WG_SUBNET} -o ${WAN_IFACE} -j MASQUERADE
WGCONF

chmod 600 "/etc/wireguard/${WG_IFACE}.conf"
systemctl enable --now "wg-quick@${WG_IFACE}"

printf '\nGateway ready.\n'
printf 'Interface: %s\n' "$WG_IFACE"
printf 'Server public key: %s\n' "$(cat /etc/wireguard/server_public.key)"
printf 'Listen port: %s/udp\n' "$WG_PORT"
printf 'Subnet: %s\n' "$WG_SUBNET"
printf 'WAN interface: %s\n' "$WAN_IFACE"
