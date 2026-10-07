from server.app.storage import DeviceStore


def test_device_store_persists_records_and_allocates_unique_addresses(tmp_path) -> None:
    path = tmp_path / "devices.db"
    store = DeviceStore(path)

    first = store.create(
        device_id="device-one",
        client_public_key="A" * 43,
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
        client_public_key="B" * 43,
        app_version="0.1.0",
        server_id="dev-1",
        created_at="2026-10-08T00:00:01+00:00",
        last_seen_at="2026-10-08T00:00:01+00:00",
        vpn_address_pool="10.67.0.0/29",
        vpn_gateway_address="10.67.0.1",
        device_token_hash="token-two",
    )
    assert second["client_address"] == "10.67.0.3/32"
    assert reopened.get("device-one")["client_public_key"] == "A" * 43
    assert len(reopened.list()) == 2
