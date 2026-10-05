# M2 gateway test

This is the fastest path to prove TunnelPilot's existing Android WireGuard client end-to-end.

## Use a temporary Linux gateway

The easiest first test is a Linux PC on the same Wi-Fi/LAN as the Android device. A public VPS works later.

The script uses `tunnelpilot0` instead of `wg0` by default so it does not intentionally collide with an existing personal WireGuard tunnel.

## Install the files

From the repository root:

```fish
unzip -o /path/to/tunnelpilot-m2-gateway-kit.zip -d .
chmod +x infra/wireguard/dev-lan-gateway.sh
```

Or copy the two files from the archive manually.

## Run the gateway

```fish
sudo ./infra/wireguard/dev-lan-gateway.sh
```

On Ubuntu/Debian it installs the required packages with `apt`. On Arch/CachyOS it installs `wireguard-tools` and `iptables-nft` without forcing a partial `pacman -Sy` upgrade.

The script creates a dedicated WireGuard interface:

```text
tunnelpilot0
10.67.0.1/24
UDP 51820
```

and a development client:

```text
10.67.0.2/32
```

The generated client config is:

```text
/root/tunnelpilot-dev-client.conf
```

It contains a private key and must never be committed to Git.

## Check the gateway

```fish
sudo wg show
ip -4 addr show tunnelpilot0
```

You should see the interface and one peer.

## Import into TunnelPilot

Open:

```text
Config → paste /root/tunnelpilot-dev-client.conf → Save configuration
```

Then:

```text
VPN → All apps → Connect
```

On the first connection Android should show the system VPN permission dialog.

## Verify the real tunnel

On the gateway:

```fish
sudo wg show
```

After Android generates traffic, the peer should show a recent handshake and RX/TX counters.

TunnelPilot should also show non-zero RX/TX counters.

Use an external IP check in a browser to verify that traffic exits through the gateway.

## Test per-app routing

1. Open `Apps`.
2. Select exactly one normal app.
3. Open `VPN`.
4. Choose `Selected apps`.
5. Tap `Reconnect with new routing`.

Expected:

```text
selected app      → WireGuard gateway
unselected apps   → normal network
TunnelPilot       → tunnel stays active
```

Do not move to automatic provisioning until this passes.

## Clean up after the test

The client private key was deliberately generated on the development gateway. After importing the config into Android, remove the generated client private key and client config from the gateway:

```fish
sudo rm -f /root/tunnelpilot-dev-client.conf
sudo rm -f /etc/wireguard/tunnelpilot0-client_private.key
sudo rm -f /etc/wireguard/tunnelpilot0-client_public.key
```

The server-side peer uses only the client's public key.

Remove the entire development gateway when finished:

```fish
sudo systemctl disable --now wg-quick@tunnelpilot0
sudo rm -f /etc/wireguard/tunnelpilot0.conf
```
