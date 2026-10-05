# WireGuard gateway provisioning

This directory will hold reproducible gateway provisioning scripts.

The production design should use:

- Linux gateway(s)
- WireGuard
- firewall rules with a default-deny posture where practical
- automated key/config rotation
- health checks
- capacity-aware server selection

Do not place generated private keys in this repository.
