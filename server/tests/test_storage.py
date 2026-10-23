import base64
import pytest

from server.app.storage import DeviceStore

KEY_ONE = base64.b64encode(b"\x01" * 32).decode("ascii")
KEY_TWO = base64.b64encode(b"\x02" * 32).decode("ascii")


def test_device_store_persists_records_and_allocates_unique_addresses(tmp_path) -> None:
    path = tmp_path / "devices.db"
    store = DeviceStore(path)

    first = store.create(
        device_id="device-one",
        client_public_key=KEY_ONE,
        app_version="0.1.0",
        server_id="dev-1",
        created_at="2026-10-08T00:00:00+00:00",
        last_seen_at="2026-10-08T00:00:00+00:00",
        vpn_address_pool="10.67.0.0/30",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="token-one",
    )
    assert first["client_address"] == "10.67.0.2/32"

    reopened = DeviceStore(path)
    second = reopened.create(
        device_id="device-two",
        client_public_key=KEY_TWO,
        app_version="0.1.0",
        server_id="dev-1",
        created_at="2026-10-08T00:00:01+00:00",
        last_seen_at="2026-10-08T00:00:01+00:00",
        vpn_address_pool="10.67.0.0/29",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="token-two",
    )
    assert second["client_address"] == "10.67.0.3/32"
    assert reopened.get("device-one")["client_public_key"] == KEY_ONE
    assert len(reopened.list()) == 2


def test_device_store_anchors_relative_path_and_verifies_integrity(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = DeviceStore("relative_dir/devices.db")
    store.create(
        device_id="device-one",
        client_public_key=KEY_ONE,
        app_version="0.2.0",
        server_id="dev-1",
        created_at="2026-10-08T00:00:00+00:00",
        last_seen_at="2026-10-08T00:00:00+00:00",
        vpn_address_pool="10.67.0.0/24",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="token-one",
    )

    other_dir = tmp_path / "subdir"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    # Even after changing cwd, store still points to the same database and passes integrity check
    rows = store.verify_integrity(vpn_address_pool="10.67.0.0/24", vpn_gateway_address="10.67.0.1")
    assert len(rows) == 1
    assert rows[0]["device_id"] == "device-one"

    # Backup creates an identical verifiable database
    backup_path = store.backup_to(tmp_path / "backups" / "devices-backup.db")
    backup_store = DeviceStore(backup_path)
    assert len(backup_store.verify_integrity(vpn_address_pool="10.67.0.0/24", vpn_gateway_address="10.67.0.1")) == 1

    # Pool mismatch is caught by verify_integrity
    with pytest.raises(RuntimeError, match="outside pool"):
        store.verify_integrity(vpn_address_pool="10.68.0.0/24", vpn_gateway_address="10.68.0.1")


def test_device_store_verify_integrity_detects_corrupted_file(tmp_path) -> None:
    path = tmp_path / "corrupt.db"
    store = DeviceStore(path)
    path.write_bytes(b"not a valid sqlite file")

    with pytest.raises(RuntimeError, match="corrupted or unreadable"):
        store.verify_integrity()


def test_device_store_backup_and_restore_from_recovers_state_and_rejects_corrupt_backup(tmp_path) -> None:
    db_path = tmp_path / "primary.db"
    store = DeviceStore(db_path)
    store.create(
        device_id="device-alpha",
        client_public_key=KEY_ONE,
        app_version="0.2.0",
        server_id="dev-1",
        created_at="2026-10-08T00:00:00+00:00",
        last_seen_at="2026-10-08T00:00:00+00:00",
        vpn_address_pool="10.67.0.0/24",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="hash-alpha",
    )

    backup_path = store.backup_to(tmp_path / "backups" / "primary.bak")
    assert (backup_path.stat().st_mode & 0o777) == 0o600

    # Delete device-alpha and insert device-beta, then restore from backup
    store.delete("device-alpha")
    store.create(
        device_id="device-beta",
        client_public_key=KEY_TWO,
        app_version="0.2.0",
        server_id="dev-1",
        created_at="2026-10-08T00:01:00+00:00",
        last_seen_at="2026-10-08T00:01:00+00:00",
        vpn_address_pool="10.67.0.0/24",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="hash-beta",
    )
    assert store.get("device-alpha") is None

    restored_rows = store.restore_from(
        backup_path,
        vpn_address_pool="10.67.0.0/24",
        vpn_gateway_address="10.67.0.1",
    )
    assert len(restored_rows) == 1
    assert restored_rows[0]["device_id"] == "device-alpha"
    assert store.get("device-alpha") is not None
    assert store.get("device-beta") is None

    # Corrupt backup is rejected before touching the active DB
    corrupt_backup = tmp_path / "backups" / "corrupt.bak"
    corrupt_backup.write_bytes(b"corrupted-backup-bytes")
    with pytest.raises(RuntimeError, match="corrupted or unreadable"):
        store.restore_from(
            corrupt_backup,
            vpn_address_pool="10.67.0.0/24",
            vpn_gateway_address="10.67.0.1",
        )
    assert store.get("device-alpha") is not None


def test_device_store_migrates_legacy_single_server_schema_and_supports_per_server_pools(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE devices (
                device_id TEXT PRIMARY KEY,
                client_public_key TEXT NOT NULL UNIQUE,
                app_version TEXT NOT NULL,
                server_id TEXT NOT NULL,
                client_address TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                provisioned INTEGER NOT NULL DEFAULT 1,
                device_token_hash TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO devices (
                device_id, client_public_key, app_version, server_id,
                client_address, created_at, last_seen_at, provisioned, device_token_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-dev-1",
                KEY_ONE,
                "0.2.0",
                "dev-lan-1",
                "10.67.0.2/32",
                "2026-10-08T00:00:00+00:00",
                "2026-10-08T00:00:00+00:00",
                1,
                "legacy-hash",
            ),
        )

    store = DeviceStore(db_path)
    migrated = store.get("legacy-dev-1")
    assert migrated is not None
    assert migrated["server_id"] == "dev-lan-1"
    assert migrated["client_address"] == "10.67.0.2/32"
    assert migrated["tier"] == "free"
    assert store.get_server("dev-lan-1") is not None

    # Create a second server and verify it can allocate from its own or overlapping pool
    store.create_server(
        server_id="eu-central-2",
        region="eu-central",
        hostname="eu2.vpn.example.com",
        port=51820,
        public_key=KEY_TWO,
        enabled=True,
        gateway_api_url="http://127.0.0.1:8788",
        gateway_agent_token="tok-2",
        vpn_address_pool="10.67.0.0/24",
        vpn_gateway_address="10.67.0.1",
        peer_capacity=2,
        tier="free",
    )
    second = store.create(
        device_id="device-eu2",
        client_public_key=KEY_TWO,
        app_version="0.2.0",
        server_id="eu-central-2",
        created_at="2026-10-08T00:01:00+00:00",
        last_seen_at="2026-10-08T00:01:00+00:00",
        vpn_address_pool="10.67.0.0/24",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="hash-2",
        peer_capacity=2,
    )
    # Because UNIQUE is now (server_id, client_address), eu-central-2 can also allocate 10.67.0.2/32
    assert second["client_address"] == "10.67.0.2/32"

    # Deleting a server with assigned devices is blocked
    with pytest.raises(ValueError, match="Cannot delete server"):
        store.delete_server("eu-central-2")

    store.delete("device-eu2")
    store.delete_server("eu-central-2")
    assert store.get_server("eu-central-2") is None
