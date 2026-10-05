#!/usr/bin/env bash
set -euo pipefail

# Add a peer to a running gateway without putting a client private key on the gateway.
# Required: CLIENT_PUBLIC_KEY and CLIENT_IP. Example CLIENT_IP=10.66.0.2/32.

: "${CLIENT_PUBLIC_KEY:?Set CLIENT_PUBLIC_KEY}"
: "${CLIENT_IP:?Set CLIENT_IP, e.g. 10.66.0.2/32}"
WG_IFACE="${WG_IFACE:-wg0}"

wg set "$WG_IFACE" peer "$CLIENT_PUBLIC_KEY" allowed-ips "$CLIENT_IP"
wg showconf "$WG_IFACE" > "/etc/wireguard/${WG_IFACE}.conf.runtime"

printf 'Peer added to %s. Persist it by adding the [Peer] block to /etc/wireguard/%s.conf.\n' "$WG_IFACE" "$WG_IFACE"
printf 'Public key: %s\n' "$CLIENT_PUBLIC_KEY"
printf 'Allowed IPs: %s\n' "$CLIENT_IP"
