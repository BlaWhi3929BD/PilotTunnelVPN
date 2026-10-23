from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import sqlite3
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeviceStore:
    """SQLite persistence layer for control-plane servers, devices, and peer tombstones."""

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
                CREATE TABLE IF NOT EXISTS servers (
                    server_id TEXT PRIMARY KEY,
                    region TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    port INTEGER NOT NULL DEFAULT 51820,
                    public_key TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    gateway_api_url TEXT,
                    gateway_agent_token TEXT,
                    vpn_address_pool TEXT NOT NULL DEFAULT '10.67.0.0/24',
                    vpn_gateway_address TEXT NOT NULL DEFAULT '10.67.0.1',
                    peer_capacity INTEGER NOT NULL DEFAULT 240,
                    tier TEXT NOT NULL DEFAULT 'free',
                    admin_managed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tombstoned_peers (
                    server_id TEXT NOT NULL,
                    client_public_key TEXT NOT NULL,
                    client_address TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (server_id, client_public_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    client_public_key TEXT NOT NULL UNIQUE,
                    app_version TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    client_address TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    provisioned INTEGER NOT NULL DEFAULT 0,
                    device_token_hash TEXT,
                    tier TEXT NOT NULL DEFAULT 'free',
                    UNIQUE(server_id, client_address)
                )
                """
            )
            self._migrate_devices_table_if_needed(connection)
            self._migrate_servers_table_if_needed(connection)
        self._restrict_permissions(self.path)

    def _migrate_devices_table_if_needed(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(devices)").fetchall()
        }
        if "device_token_hash" not in columns:
            connection.execute("ALTER TABLE devices ADD COLUMN device_token_hash TEXT")
        if "tier" not in columns:
            connection.execute("ALTER TABLE devices ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'")

        schema_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'devices'"
        ).fetchone()
        schema_sql = (schema_row["sql"] or "") if schema_row else ""
        if "UNIQUE(server_id, client_address)" not in schema_sql:
            if connection.in_transaction:
                connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    CREATE TABLE devices_v2 (
                        device_id TEXT PRIMARY KEY,
                        client_public_key TEXT NOT NULL UNIQUE,
                        app_version TEXT NOT NULL,
                        server_id TEXT NOT NULL,
                        client_address TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        provisioned INTEGER NOT NULL DEFAULT 0,
                        device_token_hash TEXT,
                        tier TEXT NOT NULL DEFAULT 'free',
                        UNIQUE(server_id, client_address)
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO devices_v2 (
                        device_id,
                        client_public_key,
                        app_version,
                        server_id,
                        client_address,
                        created_at,
                        last_seen_at,
                        provisioned,
                        device_token_hash,
                        tier
                    )
                    SELECT
                        device_id,
                        client_public_key,
                        app_version,
                        server_id,
                        client_address,
                        created_at,
                        last_seen_at,
                        provisioned,
                        device_token_hash,
                        COALESCE(tier, 'free')
                    FROM devices
                    """
                )
                connection.execute("DROP TABLE devices")
                connection.execute("ALTER TABLE devices_v2 RENAME TO devices")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _migrate_servers_table_if_needed(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(servers)").fetchall()
        }
        if "tier" not in columns:
            connection.execute("ALTER TABLE servers ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'")
        if "peer_capacity" not in columns:
            connection.execute("ALTER TABLE servers ADD COLUMN peer_capacity INTEGER NOT NULL DEFAULT 240")
        if "admin_managed" not in columns:
            connection.execute("ALTER TABLE servers ADD COLUMN admin_managed INTEGER NOT NULL DEFAULT 0")
        existing_device_servers = connection.execute(
            """
            SELECT DISTINCT server_id, MIN(created_at) AS first_seen
            FROM devices
            WHERE server_id NOT IN (SELECT server_id FROM servers)
            GROUP BY server_id
            """
        ).fetchall()
        for row in existing_device_servers:
            ts = str(row["first_seen"] or "2026-10-08T00:00:00+00:00")
            connection.execute(
                """
                INSERT OR IGNORE INTO servers (
                    server_id, region, hostname, port, public_key, enabled,
                    vpn_address_pool, vpn_gateway_address, peer_capacity, tier,
                    admin_managed, created_at, updated_at
                ) VALUES (?, 'eu-central', 'replace-with-real-gateway', 51820,
                          'replace-with-gateway-public-key', 1, '10.67.0.0/24',
                          '10.67.0.1', 240, 'free', 0, ?, ?)
                """,
                (str(row["server_id"]), ts, ts),
            )

    @staticmethod
    def _restrict_permissions(target: Path) -> None:
        try:
            if target.exists():
                target.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def validate_pool_and_gateway(
        vpn_address_pool: str,
        vpn_gateway_address: str,
        peer_capacity: int = 240,
    ) -> tuple[ipaddress.IPv4Network, ipaddress.IPv4Address]:
        try:
            network = ipaddress.ip_network(vpn_address_pool, strict=True)
        except ValueError as exc:
            raise ValueError(f"Invalid vpn_address_pool '{vpn_address_pool}': {exc}") from exc
        try:
            gateway = ipaddress.ip_address(vpn_gateway_address)
        except ValueError as exc:
            raise ValueError(f"Invalid vpn_gateway_address '{vpn_gateway_address}': {exc}") from exc
        if not isinstance(network, ipaddress.IPv4Network) or network.prefixlen >= 31:
            raise ValueError("TUNNELPILOT_VPN_ADDRESS_POOL must be an IPv4 network of at least /30")
        if not isinstance(gateway, ipaddress.IPv4Address) or gateway not in network:
            raise ValueError(
                "TUNNELPILOT_VPN_GATEWAY_ADDRESS must be inside TUNNELPILOT_VPN_ADDRESS_POOL"
            )
        if peer_capacity < 1:
            raise ValueError("peer_capacity must be at least 1")
        return network, gateway

    # --- Server catalog persistence ---

    def ensure_default_server(
        self,
        *,
        server_id: str,
        region: str,
        hostname: str,
        port: int,
        public_key: str,
        enabled: bool,
        gateway_api_url: str | None,
        gateway_agent_token: str | None,
        vpn_address_pool: str,
        vpn_gateway_address: str,
        peer_capacity: int = 240,
        tier: str = "free",
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM servers WHERE server_id = ?",
                    (server_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO servers (
                            server_id,
                            region,
                            hostname,
                            port,
                            public_key,
                            enabled,
                            gateway_api_url,
                            gateway_agent_token,
                            vpn_address_pool,
                            vpn_gateway_address,
                            peer_capacity,
                            tier,
                            admin_managed,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                        """,
                        (
                            server_id,
                            region,
                            hostname,
                            int(port),
                            public_key,
                            int(enabled),
                            gateway_api_url,
                            gateway_agent_token,
                            vpn_address_pool,
                            vpn_gateway_address,
                            int(peer_capacity),
                            tier,
                            now,
                            now,
                        ),
                    )
                elif int(existing["admin_managed"]) == 0:
                    connection.execute(
                        """
                        UPDATE servers
                        SET region = ?,
                            hostname = ?,
                            port = ?,
                            public_key = ?,
                            enabled = ?,
                            gateway_api_url = ?,
                            gateway_agent_token = ?,
                            vpn_address_pool = ?,
                            vpn_gateway_address = ?,
                            peer_capacity = ?,
                            tier = ?,
                            updated_at = ?
                        WHERE server_id = ?
                        """,
                        (
                            region,
                            hostname,
                            int(port),
                            public_key,
                            int(enabled),
                            gateway_api_url,
                            gateway_agent_token,
                            vpn_address_pool,
                            vpn_gateway_address,
                            int(peer_capacity),
                            tier,
                            now,
                            server_id,
                        ),
                    )

                # Also ensure any legacy server_id referenced in existing devices (e.g. 'dev-lan-1')
                # is present in the servers catalog so existing devices are never orphaned on migration.
                orphan_server_ids = [
                    str(r[0])
                    for r in connection.execute(
                        """
                        SELECT DISTINCT d.server_id
                        FROM devices d
                        LEFT JOIN servers s ON s.server_id = d.server_id
                        WHERE s.server_id IS NULL
                        """
                    ).fetchall()
                ]
                for orphan_id in orphan_server_ids:
                    connection.execute(
                        """
                        INSERT INTO servers (
                            server_id,
                            region,
                            hostname,
                            port,
                            public_key,
                            enabled,
                            gateway_api_url,
                            gateway_agent_token,
                            vpn_address_pool,
                            vpn_gateway_address,
                            peer_capacity,
                            tier,
                            admin_managed,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                        """,
                        (
                            orphan_id,
                            region,
                            hostname,
                            int(port),
                            public_key,
                            1,
                            gateway_api_url,
                            gateway_agent_token,
                            vpn_address_pool,
                            vpn_gateway_address,
                            int(peer_capacity),
                            "free",
                            now,
                            now,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_server(server_id) or {}

    def get_server(self, server_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM servers WHERE server_id = ?",
                    (server_id,),
                ).fetchone()
            )

    def list_servers(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM servers"
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY server_id"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def count_devices_for_server(self, server_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM devices WHERE server_id = ?",
                (server_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def create_server(
        self,
        *,
        server_id: str,
        region: str,
        hostname: str,
        port: int = 51820,
        public_key: str,
        enabled: bool = True,
        gateway_api_url: str | None = None,
        gateway_agent_token: str | None = None,
        vpn_address_pool: str = "10.67.0.0/24",
        vpn_gateway_address: str = "10.67.0.1",
        peer_capacity: int = 240,
        tier: str = "free",
    ) -> dict[str, Any]:
        self.validate_pool_and_gateway(vpn_address_pool, vpn_gateway_address, peer_capacity)
        now = _utc_now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT server_id FROM servers WHERE server_id = ?",
                    (server_id,),
                ).fetchone()
                if existing is not None:
                    raise ValueError(f"Server '{server_id}' already exists")
                connection.execute(
                    """
                    INSERT INTO servers (
                        server_id,
                        region,
                        hostname,
                        port,
                        public_key,
                        enabled,
                        gateway_api_url,
                        gateway_agent_token,
                        vpn_address_pool,
                        vpn_gateway_address,
                        peer_capacity,
                        tier,
                        admin_managed,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        server_id,
                        region,
                        hostname,
                        int(port),
                        public_key,
                        int(enabled),
                        gateway_api_url,
                        gateway_agent_token,
                        vpn_address_pool,
                        vpn_gateway_address,
                        int(peer_capacity),
                        tier,
                        now,
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_server(server_id) or {}

    def update_server(
        self,
        server_id: str,
        *,
        region: str | None = None,
        hostname: str | None = None,
        port: int | None = None,
        public_key: str | None = None,
        enabled: bool | None = None,
        gateway_api_url: str | None = None,
        update_gateway_api_url: bool = False,
        gateway_agent_token: str | None = None,
        update_gateway_agent_token: bool = False,
        vpn_address_pool: str | None = None,
        vpn_gateway_address: str | None = None,
        peer_capacity: int | None = None,
        tier: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_server(server_id)
        if current is None:
            raise KeyError(f"Server '{server_id}' not found")

        effective_pool = vpn_address_pool if vpn_address_pool is not None else str(current["vpn_address_pool"])
        effective_gw = vpn_gateway_address if vpn_gateway_address is not None else str(current["vpn_gateway_address"])
        effective_cap = int(peer_capacity) if peer_capacity is not None else int(current["peer_capacity"])
        pool_net, gw_ip = self.validate_pool_and_gateway(effective_pool, effective_gw, effective_cap)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                device_rows = connection.execute(
                    "SELECT device_id, client_address FROM devices WHERE server_id = ?",
                    (server_id,),
                ).fetchall()
                if len(device_rows) > effective_cap:
                    raise ValueError(
                        f"Cannot reduce peer_capacity to {effective_cap} while {len(device_rows)} devices are assigned"
                    )
                for drow in device_rows:
                    addr_net = ipaddress.ip_network(str(drow["client_address"]), strict=True)
                    if addr_net.network_address not in pool_net or addr_net.network_address == gw_ip:
                        raise ValueError(
                            f"Assigned device '{drow['device_id']}' ({drow['client_address']}) is incompatible with updated pool/gateway"
                        )

                fields: list[str] = ["updated_at = ?", "admin_managed = 1"]
                values: list[Any] = [_utc_now_iso()]
                updates: dict[str, Any] = {
                    "region": region,
                    "hostname": hostname,
                    "port": port,
                    "public_key": public_key,
                    "enabled": None if enabled is None else int(enabled),
                    "vpn_address_pool": vpn_address_pool,
                    "vpn_gateway_address": vpn_gateway_address,
                    "peer_capacity": peer_capacity,
                    "tier": tier,
                }
                for col, val in updates.items():
                    if val is not None:
                        fields.append(f"{col} = ?")
                        values.append(val)
                if update_gateway_api_url:
                    fields.append("gateway_api_url = ?")
                    values.append(gateway_api_url)
                if update_gateway_agent_token:
                    fields.append("gateway_agent_token = ?")
                    values.append(gateway_agent_token)
                values.append(server_id)
                connection.execute(
                    f"UPDATE servers SET {', '.join(fields)} WHERE server_id = ?",
                    values,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_server(server_id) or {}

    def delete_server(self, server_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT server_id FROM servers WHERE server_id = ?",
                    (server_id,),
                ).fetchone()
                if existing is None:
                    raise KeyError(f"Server '{server_id}' not found")
                assigned_count = connection.execute(
                    "SELECT COUNT(*) FROM devices WHERE server_id = ?",
                    (server_id,),
                ).fetchone()[0]
                if int(assigned_count) > 0:
                    raise ValueError(
                        f"Cannot delete server '{server_id}' while {assigned_count} device(s) are still assigned; migrate or revoke them first"
                    )
                connection.execute("DELETE FROM tombstoned_peers WHERE server_id = ?", (server_id,))
                connection.execute("DELETE FROM servers WHERE server_id = ?", (server_id,))
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    # --- Tombstone outbox for peer cleanup after migration ---

    def add_tombstone(self, server_id: str, client_public_key: str, client_address: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tombstoned_peers (
                    server_id,
                    client_public_key,
                    client_address,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (server_id, client_public_key, client_address, _utc_now_iso()),
            )

    def list_tombstones(self, server_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tombstoned_peers WHERE server_id = ? ORDER BY created_at",
                (server_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove_tombstone(self, server_id: str, client_public_key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM tombstoned_peers WHERE server_id = ? AND client_public_key = ?",
                (server_id, client_public_key),
            )

    # --- Device persistence ---

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

    def list(self, *, server_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if server_id is not None:
                rows = connection.execute(
                    "SELECT * FROM devices WHERE server_id = ? ORDER BY created_at, device_id",
                    (server_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM devices ORDER BY created_at, device_id"
                ).fetchall()
        return [dict(row) for row in rows]

    def verify_integrity(
        self,
        *,
        vpn_address_pool: str | None = None,
        vpn_gateway_address: str | None = None,
        server_id: str | None = None,
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

        override_pool = (
            ipaddress.ip_network(vpn_address_pool, strict=True)
            if vpn_address_pool is not None
            else None
        )
        override_gateway = (
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
                server_rows = {
                    str(row["server_id"]): dict(row)
                    for row in connection.execute("SELECT * FROM servers").fetchall()
                }
                if server_id is not None:
                    rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT * FROM devices WHERE server_id = ? ORDER BY created_at, device_id",
                            (server_id,),
                        ).fetchall()
                    ]
                else:
                    rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT * FROM devices ORDER BY created_at, device_id"
                        ).fetchall()
                    ]
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"SQLite database is corrupted or unreadable: {exc}") from exc

        seen_keys: set[str] = set()
        seen_server_addresses: set[tuple[str, str]] = set()
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

            row_server_id = str(row.get("server_id", ""))
            srv_meta = server_rows.get(row_server_id)
            if override_pool is not None and (server_id is not None or srv_meta is None):
                pool_network = override_pool
            elif srv_meta is not None:
                pool_network = ipaddress.ip_network(str(srv_meta["vpn_address_pool"]), strict=True)
            else:
                pool_network = override_pool

            if override_gateway is not None and (server_id is not None or srv_meta is None):
                gateway_ip = override_gateway
            elif srv_meta is not None:
                gateway_ip = ipaddress.ip_address(str(srv_meta["vpn_gateway_address"]))
            else:
                gateway_ip = override_gateway

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
            pair = (row_server_id, client_addr)
            if pair in seen_server_addresses:
                raise RuntimeError(f"Duplicate client_address detected on server {row_server_id}: {client_addr}")
            seen_server_addresses.add(pair)

        return rows

    def backup_to(self, destination: str | Path) -> Path:
        dest_path = Path(destination).expanduser().resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as src_conn:
            dst_conn = sqlite3.connect(dest_path, timeout=10.0)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        self._restrict_permissions(dest_path)
        return dest_path

    def restore_from(
        self,
        source: str | Path,
        *,
        vpn_address_pool: str | None = None,
        vpn_gateway_address: str | None = None,
    ) -> list[dict[str, Any]]:
        src_path = Path(source).expanduser().resolve()
        if not src_path.exists():
            raise RuntimeError(f"Backup SQLite file does not exist: {src_path}")
        try:
            source_store = DeviceStore(src_path)
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"SQLite database is corrupted or unreadable: {exc}") from exc
        source_store.verify_integrity(
            vpn_address_pool=vpn_address_pool,
            vpn_gateway_address=vpn_gateway_address,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with source_store._connect() as src_conn:
            dst_conn = sqlite3.connect(self.path, timeout=10.0)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        self._initialize()
        return self.verify_integrity(
            vpn_address_pool=vpn_address_pool,
            vpn_gateway_address=vpn_gateway_address,
        )

    @staticmethod
    def _allocate_ip_in_transaction(
        connection: sqlite3.Connection,
        *,
        server_id: str,
        network: ipaddress.IPv4Network,
        gateway: ipaddress.IPv4Address,
        peer_capacity: int | None = None,
        exclude_device_id: str | None = None,
    ) -> str:
        if exclude_device_id is not None:
            rows = connection.execute(
                "SELECT client_address FROM devices WHERE server_id = ? AND device_id != ?",
                (server_id, exclude_device_id),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT client_address FROM devices WHERE server_id = ?",
                (server_id,),
            ).fetchall()
        used = {str(row[0]) for row in rows}
        if peer_capacity is not None and len(used) >= peer_capacity:
            raise RuntimeError(f"Server '{server_id}' has reached its peer capacity ({peer_capacity})")

        for host in network.hosts():
            value = str(host)
            if host != gateway and f"{value}/32" not in used:
                return f"{value}/32"
        raise RuntimeError("No VPN client addresses are currently available")

    def allocate_address_for_server(
        self,
        *,
        server_id: str,
        vpn_address_pool: str,
        vpn_gateway_address: str,
        peer_capacity: int | None = None,
        exclude_device_id: str | None = None,
    ) -> str:
        try:
            network, gateway = self.validate_pool_and_gateway(
                vpn_address_pool,
                vpn_gateway_address,
                peer_capacity or 240,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        with self._connect() as connection:
            return self._allocate_ip_in_transaction(
                connection,
                server_id=server_id,
                network=network,
                gateway=gateway,
                peer_capacity=peer_capacity,
                exclude_device_id=exclude_device_id,
            )

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
        peer_capacity: int | None = None,
        tier: str = "free",
    ) -> dict[str, Any]:
        try:
            network, gateway = self.validate_pool_and_gateway(
                vpn_address_pool,
                vpn_gateway_address,
                peer_capacity or 240,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT device_id FROM devices WHERE client_public_key = ?",
                    (client_public_key,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("client_public_key is already registered to another device_id")

                client_address = self._allocate_ip_in_transaction(
                    connection,
                    server_id=server_id,
                    network=network,
                    gateway=gateway,
                    peer_capacity=peer_capacity,
                )

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
                        device_token_hash,
                        tier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
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
                        tier,
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
        tier: str | None = None,
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
            "tier": tier,
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
