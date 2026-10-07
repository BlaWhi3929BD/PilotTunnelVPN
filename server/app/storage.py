from __future__ import annotations

import ipaddress
import sqlite3
from pathlib import Path
from typing import Any


class DeviceStore:
    """Small SQLite persistence layer for control-plane device state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

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
            connection.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?",
                values,
            )

    def delete(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
