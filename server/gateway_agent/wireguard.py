from __future__ import annotations

import base64
import binascii
import ipaddress
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Runner = Callable[..., subprocess.CompletedProcess[str]]


def validate_public_key(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("public_key must be standard base64") from exc
    if len(decoded) != 32:
        raise ValueError("public_key must decode to exactly 32 bytes")
    return value


def normalize_allowed_ip(value: str) -> str:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise ValueError("allowed_ip must be a valid network in CIDR notation") from exc

    if network.version != 4 or network.prefixlen != 32:
        raise ValueError("allowed_ip must be a single IPv4 /32 address")
    return str(network)


@dataclass(slots=True)
class WireGuardController:
    interface: str = "tunnelpilot0"
    binary: str = "wg"
    runner: Runner = subprocess.run
    timeout_seconds: float = 5.0

    def _run(self, args: Sequence[str]) -> None:
        try:
            self.runner(
                list(args),
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"WireGuard command not found: {self.binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("WireGuard command timed out") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            detail = stderr or f"exit status {exc.returncode}"
            raise RuntimeError(f"WireGuard command failed: {detail}") from exc

    def ensure_available(self) -> None:
        self._run([self.binary, "show", self.interface])

    def add_peer(self, public_key: str, allowed_ip: str) -> None:
        public_key = validate_public_key(public_key)
        allowed_ip = normalize_allowed_ip(allowed_ip)
        self._run(
            [
                self.binary,
                "set",
                self.interface,
                "peer",
                public_key,
                "allowed-ips",
                allowed_ip,
            ]
        )

    def remove_peer(self, public_key: str) -> None:
        public_key = validate_public_key(public_key)
        self._run([self.binary, "set", self.interface, "peer", public_key, "remove"])
