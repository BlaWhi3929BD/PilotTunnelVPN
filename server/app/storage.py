from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from contextlib import contextmanager
import ipaddress
import sqlite3
from pathlib import Path
from typing import Any


class DeviceStore:
    """Small SQLite persistence layer for control-plane device state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    client_public_key TEXT NOT NULL UNIQUE,
                    app_version TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    client_address TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    provisioned INTEGER NOT NULL DEFAULT 0,
                    device_token_hash TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(devices)").fetchall()
            }
            if "device_token_hash" not in columns:
                connection.execute("ALTER TABLE devices ADD COLUMN device_token_hash TEXT")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get(self, device_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM devices WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
            )

    def find_by_public_key(self, public_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM devices WHERE client_public_key = ?",
                    (public_key,),
                ).fetchone()
            )

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM devices ORDER BY created_at, device_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_integrity(
        self,
        *,
        vpn_address_pool: str | None = None,
        vpn_gateway_address: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            raise RuntimeError(f"SQLite database file does not exist: {self.path}")
        try:
            with self.path.open("rb") as handle:
                header = handle.read(16)
        except OSError as exc:
            raise RuntimeError(f"SQLite database is corrupted or unreadable: {exc}") from exc
        if len(header) > 0 and header != b"SQLite format 3\x00":
            raise RuntimeError("SQLite database is corrupted or unreadable: invalid file header")

        pool_network = (
            ipaddress.ip_network(vpn_address_pool, strict=True)
            if vpn_address_pool is not None
            else None
        )
        gateway_ip = (
            ipaddress.ip_address(vpn_gateway_address)
            if vpn_gateway_address is not None
            else None
        )

        try:
            with self._connect() as connection:
                check_rows = connection.execute("PRAGMA quick_check").fetchall()
                results = [str(row[0]) for row in check_rows]
                if results != ["ok"]:
                    raise RuntimeError(f"SQLite integrity check failed: {', '.join(results)}")
                rows = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM devices ORDER BY created_at, device_id"
                    ).fetchall()
                ]
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"SQLite database is corrupted or unreadable: {exc}") from exc

        seen_keys: set[str] = set()
        seen_addresses: set[str] = set()
        for row in rows:
            pub_key = str(row.get("client_public_key", ""))
            try:
                decoded = base64.b64decode(pub_key, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError(
                    f"Corrupted client_public_key for device {row.get('device_id')}"
                ) from exc
            if len(decoded) != 32:
                raise RuntimeError(
                    f"Invalid client_public_key length for device {row.get('device_id')}"
                )
            if pub_key in seen_keys:
                raise RuntimeError(f"Duplicate client_public_key detected: {pub_key}")
            seen_keys.add(pub_key)

            client_addr = str(row.get("client_address", ""))
            try:
                addr_net = ipaddress.ip_network(client_addr, strict=True)
            except ValueError as exc:
                raise RuntimeError(
                    f"Corrupted client_address '{client_addr}' for device {row.get('device_id')}"
                ) from exc
            if addr_net.version != 4 or addr_net.prefixlen != 32:
                raise RuntimeError(
                    f"Non-/32 IPv4 client_address '{client_addr}' for device {row.get('device_id')}"
                )
            host_ip = addr_net.network_address
            if pool_network is not None and host_ip not in pool_network:
                raise RuntimeError(
                    f"Device {row.get('device_id')} address {client_addr} is outside pool {pool_network}"
                )
            if gateway_ip is not None and host_ip == gateway_ip:
                raise RuntimeError(
                    f"Device {row.get('device_id')} address {client_addr} collides with gateway {gateway_ip}"
                )
            if client_addr in seen_addresses:
                raise RuntimeError(f"Duplicate client_address detected: {client_addr}")
            seen_addresses.add(client_addr)

        return rows

    def backup_to(self, destination: str | Path) -> Path:
        dest_path = Path(destination).expanduser().resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as src_conn:
            with sqlite3.connect(dest_path, timeout=10.0) as dst_conn:
                src_conn.backup(dst_conn)
        return dest_path

    def create(
        self,
        *,
        device_id: str,
        client_public_key: str,
        app_version: str,
        server_id: str,
        created_at: str,
        last_seen_at: str,
        vpn_address_pool: str,
        vpn_gateway_address: str,
        device_token_hash: str,
    ) -> dict[str, Any]:
        network = ipaddress.ip_network(vpn_address_pool, strict=True)
        gateway = ipaddress.ip_address(vpn_gateway_address)
        if network.version != 4 or network.prefixlen >= 31:
            raise RuntimeError("TUNNELPILOT_VPN_ADDRESS_POOL must be an IPv4 network of at least /30")
        if gateway.version != 4 or gateway not in network:
            raise RuntimeError(
                "TUNNELPILOT_VPN_GATEWAY_ADDRESS must be inside TUNNELPILOT_VPN_ADDRESS_POOL"
            )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT device_id FROM devices WHERE client_public_key = ?",
                    (client_public_key,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("client_public_key is already registered to another device_id")

                used = {
                    row[0]
                    for row in connection.execute("SELECT client_address FROM devices").fetchall()
                }
                client_address: str | None = None
                for host in network.hosts():
                    value = str(host)
                    if host != gateway and f"{value}/32" not in used:
                        client_address = f"{value}/32"
                        break
                if client_address is None:
                    raise RuntimeError("No VPN client addresses are currently available")

                connection.execute(
                    """
                    INSERT INTO devices (
                        device_id,
                        client_public_key,
                        app_version,
                        server_id,
                        client_address,
                        created_at,
                        last_seen_at,
                        provisioned,
                        device_token_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        device_id,
                        client_public_key,
                        app_version,
                        server_id,
                        client_address,
                        created_at,
                        last_seen_at,
                        device_token_hash,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return self.get(device_id) or {}

    def update(
        self,
        *,
        device_id: str,
        client_public_key: str | None = None,
        app_version: str | None = None,
        server_id: str | None = None,
        client_address: str | None = None,
        last_seen_at: str | None = None,
        provisioned: bool | None = None,
        device_token_hash: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        updates = {
            "client_public_key": client_public_key,
            "app_version": app_version,
            "server_id": server_id,
            "client_address": client_address,
            "last_seen_at": last_seen_at,
            "provisioned": None if provisioned is None else int(provisioned),
            "device_token_hash": device_token_hash,
        }
        for name, value in updates.items():
            if value is not None:
                fields.append(f"{name} = ?")
                values.append(value)
        if not fields:
            return
        values.append(device_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?",
                    values,
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError(
                    "client_public_key or client_address is already registered to another device_id"
                ) from exc
            except Exception:
                connection.rollback()
                raise

    def delete(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
