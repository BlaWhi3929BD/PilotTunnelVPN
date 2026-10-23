#!/usr/bin/env bash
set -euo pipefail

echo "Applying WireGuard forwarding, NAT, and TCP MSS clamping rules..."

# 1. Enable IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

# 2. Allow forwarding to/from tunnelpilot0
sudo iptables -C FORWARD -i tunnelpilot0 -j ACCEPT 2>/dev/null || sudo iptables -A FORWARD -i tunnelpilot0 -j ACCEPT
sudo iptables -C FORWARD -o tunnelpilot0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || sudo iptables -A FORWARD -o tunnelpilot0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -C FORWARD -o tunnelpilot0 -j ACCEPT 2>/dev/null || sudo iptables -A FORWARD -o tunnelpilot0 -j ACCEPT

# 3. NAT MASQUERADE for VPN subnet out of any WAN interface
sudo iptables -t nat -C POSTROUTING -s 10.67.0.0/24 ! -o tunnelpilot0 -j MASQUERADE 2>/dev/null || sudo iptables -t nat -A POSTROUTING -s 10.67.0.0/24 ! -o tunnelpilot0 -j MASQUERADE

# 4. Critical fix for PMTU blackhole: Clamp TCP MSS to MTU size (eliminates packet drops on Reddit/Telegram/HTTPS)
sudo iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

echo "Gateway forwarding, NAT, and TCP MSS clamping successfully configured."
