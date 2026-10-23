import base64

import pytest
from fastapi.testclient import TestClient

from server.app import main
from server.app.storage import DeviceStore


client = TestClient(main.app)

VALID_PUBLIC_KEY = base64.b64encode(bytes(range(32))).decode()
ANOTHER_PUBLIC_KEY = base64.b64encode(bytes(range(32, 64))).decode()


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch) -> None:
    store = DeviceStore(tmp_path / "devices.db")
    monkeypatch.setattr(main, "DEVICE_STORE", store)
    main.DEVICES.clear()
    main.CONTROL_PLANE_TOKEN = None
    main.GATEWAY_AGENT_URL = None
    main.GATEWAY_AGENT_TOKEN = None
    main.ENVIRONMENT = "development"
    main.ALLOW_OPEN_REGISTRATION = False
    main.ALLOW_NONSTANDARD_WG_INTERFACE = False
    main.VPN_ADDRESS_POOL = "10.67.0.0/24"
    main.VPN_GATEWAY_ADDRESS = "10.67.0.1"
    main.SERVERS[0].enabled = True
    main.SERVERS[0].gateway_api_url = None
    main.SERVERS[0].hostname = "replace-with-real-gateway"
    main.SERVERS[0].public_key = "replace-with-gateway-public-key"


def registration(
    device_id: str = "device-1234",
    public_key: str = VALID_PUBLIC_KEY,
) -> dict[str, str]:
    return {
        "device_id": device_id,
        "client_public_key": public_key,
        "app_version": "0.1.0",
    }


def test_registers_device_and_assigns_server_and_address() -> None:
    response = client.post("/v1/devices", json=registration())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["server"]["id"] == "dev-1"
    assert body["client_address"] == "10.67.0.2/32"
    assert body["provisioned"] is False
    assert len(body["device_token"]) >= 32


def test_existing_device_requires_device_token() -> None:
    first = client.post("/v1/devices", json=registration())
    token = first.json()["device_token"]

    unauthorized = client.post("/v1/devices", json=registration())
    authorized = client.post(
        "/v1/devices",
        json=registration(),
        headers={"X-Device-Token": token},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["device_token"] is None
    assert authorized.json()["client_address"] == "10.67.0.2/32"


def test_different_key_for_existing_device_is_rejected() -> None:
    first = client.post("/v1/devices", json=registration())
    token = first.json()["device_token"]

    response = client.post(
        "/v1/devices",
        json=registration(public_key=ANOTHER_PUBLIC_KEY),
        headers={"X-Device-Token": token},
    )

    assert response.status_code == 409
    assert "different public key" in response.json()["detail"]


def test_public_key_cannot_be_reused_for_another_device_id() -> None:
    first = client.post("/v1/devices", json=registration())
    second = client.post(
        "/v1/devices",
        json=registration(device_id="device-5678"),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "another device_id" in second.json()["detail"]


@pytest.mark.parametrize(
    "public_key",
    [
        "not-base64",
        base64.b64encode(b"too-short").decode(),
        base64.b64encode(bytes(31)).decode(),
        base64.b64encode(bytes(33)).decode(),
    ],
)
def test_invalid_public_key_is_rejected(public_key: str) -> None:
    response = client.post("/v1/devices", json=registration(public_key=public_key))
    assert response.status_code == 422


def test_missing_server_returns_503() -> None:
    main.SERVERS[0].enabled = False
    response = client.post("/v1/devices", json=registration())
    assert response.status_code == 503


def test_control_plane_token_can_be_required() -> None:
    main.CONTROL_PLANE_TOKEN = "test-token"

    unauthorized = client.post("/v1/devices", json=registration())
    authorized = client.post(
        "/v1/devices",
        json=registration(),
        headers={"Authorization": "Bearer test-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_registration_provisions_peer_and_reprovisions_after_control_plane_restart(monkeypatch, tmp_path) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    calls: list[tuple[str, str, dict[str, str] | None, dict[str, str]]] = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 0,
                "peer_capacity": 240,
                "capacity_remaining": 240,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            assert path == "/healthz"
            return FakeResponse()

        def request(self, method, path, *, headers, json=None):
            calls.append((method, path, json, headers))
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    first = client.post("/v1/devices", json=registration())
    token = first.json()["device_token"]

    # Simulate a control-plane restart by replacing the in-memory cache with a reopened database.
    monkeypatch.setattr(main, "DEVICE_STORE", DeviceStore(tmp_path / "devices.db"))
    # Re-seed the persistent store from the original fixture database.
    original = main.DEVICE_STORE.list()
    if not original:
        # The reopened DB above is intentionally empty; recover from the first store via DEVICES.
        record = main.DEVICES["device-1234"]
        main.DEVICE_STORE.create(
            device_id=record.device_id,
            client_public_key=record.client_public_key,
            app_version=record.app_version,
            server_id=record.server_id,
            created_at=record.created_at.isoformat(),
            last_seen_at=record.last_seen_at.isoformat(),
            vpn_address_pool="10.67.0.0/24",
            vpn_gateway_address="10.67.0.1",
            device_token_hash=record.device_token_hash or "",
        )
    main.DEVICES.clear()

    second = client.post(
        "/v1/devices",
        json=registration(),
        headers={"X-Device-Token": token},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["client_address"] == "10.67.0.2/32"
    assert [call[0:2] for call in calls].count(("POST", "/v1/peers")) == 2


def test_revoke_device_removes_provisioned_peer(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    calls: list[tuple[str, str]] = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 0,
                "peer_capacity": 240,
                "capacity_remaining": 240,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return FakeResponse()

        def request(self, method, path, *, headers, json=None):
            calls.append((method, path))
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)
    main.CONTROL_PLANE_TOKEN = "admin-token"

    created = client.post(
        "/v1/devices",
        json=registration(),
        headers={"Authorization": "Bearer admin-token"},
    )
    assert created.status_code == 200

    revoked = client.delete(
        "/v1/devices/device-1234",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert revoked.status_code == 200
    assert "device-1234" not in main.DEVICES
    assert ("DELETE", f"/v1/peers?public_key={VALID_PUBLIC_KEY[:-1]}%3D") in calls


def test_revoke_device_with_device_token_succeeds(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"
    main.CONTROL_PLANE_TOKEN = None

    class LocalResponse:
        def __init__(self, status_code: int = 200, text: str = "ok"):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 0,
                "peer_capacity": 240,
                "capacity_remaining": 240,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return LocalResponse()

        def request(self, method, path, *, headers, json=None):
            return LocalResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    created = client.post("/v1/devices", json=registration())
    assert created.status_code == 200
    token = created.json()["device_token"]

    # Anonymous revoke is rejected with 401
    anonymous = client.delete("/v1/devices/device-1234")
    assert anonymous.status_code == 401

    # Invalid device token is rejected with 401
    bad_token = client.delete("/v1/devices/device-1234", headers={"X-Device-Token": "bad-token"})
    assert bad_token.status_code == 401

    # Valid device token succeeds
    revoked = client.delete("/v1/devices/device-1234", headers={"X-Device-Token": token})
    assert revoked.status_code == 200
    assert main.DEVICE_STORE.get("device-1234") is None


def test_revoke_device_gateway_failure_retains_record_unless_forced(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"
    main.CONTROL_PLANE_TOKEN = "admin-token"

    class LocalResponse:
        def __init__(self, status_code: int = 200, text: str = "ok"):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 0,
                "peer_capacity": 240,
                "capacity_remaining": 240,
            }

    class FlakyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return LocalResponse()

        def request(self, method, path, *, headers, json=None):
            if method == "DELETE":
                return LocalResponse(status_code=502, text="Gateway offline")
            return LocalResponse(status_code=200)

    monkeypatch.setattr(main.httpx, "Client", FlakyClient)

    created = client.post(
        "/v1/devices",
        json=registration(),
        headers={"Authorization": "Bearer admin-token"},
    )
    assert created.status_code == 200
    token = created.json()["device_token"]

    # 1. Gateway fails -> returns 502, device record is NOT deleted
    failed = client.delete(
        "/v1/devices/device-1234",
        headers={"X-Device-Token": token},
    )
    assert failed.status_code == 502
    assert main.DEVICE_STORE.get("device-1234") is not None

    # 2. Force delete -> returns 200, record is deleted
    forced = client.delete(
        "/v1/devices/device-1234?force=true",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert forced.status_code == 200
    assert main.DEVICE_STORE.get("device-1234") is None


def test_rotate_device_key_requires_device_token_and_replaces_gateway_peer(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    new_public_key = base64.b64encode(bytes(range(64, 96))).decode()
    calls: list[tuple[str, str, dict[str, str] | None, dict[str, str]]] = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 1,
                "peer_capacity": 240,
                "capacity_remaining": 239,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return FakeResponse()

        def request(self, method, path, *, headers, json=None):
            calls.append((method, path, json, headers))
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    created = client.post("/v1/devices", json=registration())
    token = created.json()["device_token"]

    unauthorized = client.post(
        "/v1/devices/device-1234/rotate",
        json={"client_public_key": new_public_key, "app_version": "0.2.0"},
    )
    rotated = client.post(
        "/v1/devices/device-1234/rotate",
        json={"client_public_key": new_public_key, "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )

    assert unauthorized.status_code == 401
    assert rotated.status_code == 200
    assert rotated.json()["status"] == "rotated"
    assert rotated.json()["client_address"] == "10.67.0.2/32"
    record = main.DEVICE_STORE.get("device-1234")
    assert record["client_public_key"] == new_public_key
    # New peer must be installed BEFORE old peer is removed
    assert calls[-2][0:2] == ("POST", "/v1/peers")
    assert calls[-2][2] == {"public_key": new_public_key, "allowed_ip": "10.67.0.2/32"}
    assert calls[-1][0:2] == ("DELETE", f"/v1/peers?public_key={VALID_PUBLIC_KEY[:-1]}%3D")


def test_rotate_device_key_preserves_old_peer_when_gateway_rejects_new_key(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    active_peers = {VALID_PUBLIC_KEY}
    delete_calls: list[str] = []

    class FakeResponse:
        def __init__(self, status_code: int = 200, text: str = "ok"):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": len(active_peers),
                "peer_capacity": 240,
                "capacity_remaining": 240 - len(active_peers),
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return FakeResponse()

        def request(self, method, path, *, headers, json=None):
            if method == "POST" and path == "/v1/peers":
                if json and json.get("public_key") == ANOTHER_PUBLIC_KEY:
                    return FakeResponse(status_code=502, text="Gateway failed to add new peer")
                return FakeResponse()
            if method == "DELETE":
                delete_calls.append(path)
                return FakeResponse()
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    created = client.post("/v1/devices", json=registration())
    token = created.json()["device_token"]

    failed = client.post(
        "/v1/devices/device-1234/rotate",
        json={"client_public_key": ANOTHER_PUBLIC_KEY, "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )

    assert failed.status_code == 502
    assert delete_calls == []
    assert VALID_PUBLIC_KEY in active_peers
    assert main.DEVICE_STORE.get("device-1234")["client_public_key"] == VALID_PUBLIC_KEY


def test_rotate_device_key_rejects_key_used_by_another_device(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = None
    first = client.post("/v1/devices", json=registration())
    second_key = ANOTHER_PUBLIC_KEY
    second = client.post("/v1/devices", json=registration(device_id="device-5678", public_key=second_key))
    token = first.json()["device_token"]

    response = client.post(
        "/v1/devices/device-1234/rotate",
        json={"client_public_key": second_key, "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert response.status_code == 409
    assert "another device_id" in response.json()["detail"]


def test_register_device_gateway_failure_does_not_strand_new_device(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    should_fail = True

    class FlakyResponse:
        def __init__(self, status_code: int, text: str = "ok"):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 0,
                "peer_capacity": 240,
                "capacity_remaining": 240,
            }

    class FlakyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return FlakyResponse(200)

        def request(self, method, path, *, headers, json=None):
            if should_fail and method == "POST" and path == "/v1/peers":
                return FlakyResponse(502, "Gateway error")
            return FlakyResponse(200)

        def delete(self, path, *, headers=None):
            return FlakyResponse(200)

    monkeypatch.setattr(main.httpx, "Client", FlakyClient)

    # 1. First registration attempt fails on gateway provisioning
    failed = client.post("/v1/devices", json=registration())
    assert failed.status_code == 502

    # 2. Assert device was NOT stranded in DB or cache
    assert main.DEVICE_STORE.get("device-1234") is None
    assert "device-1234" not in main.DEVICES

    # 3. Gateway is restored; repeat registration with same device ID succeeds as new enrollment
    should_fail = False
    succeeded = client.post("/v1/devices", json=registration())
    assert succeeded.status_code == 200
    assert succeeded.json()["status"] == "accepted"
    assert succeeded.json()["device_token"] is not None
    assert main.DEVICE_STORE.get("device-1234") is not None


def test_reconcile_server_is_non_destructive_by_default_and_supports_dry_run(monkeypatch) -> None:
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    stale_key = base64.b64encode(b"\x99" * 32).decode("ascii")
    foreign_key = base64.b64encode(b"\x88" * 32).decode("ascii")
    second_key = base64.b64encode(b"\x22" * 32).decode("ascii")
    gateway_peers: dict[str, list[str]] = {}
    calls: list[tuple[str, str, dict | None]] = []

    class FakeGatewayResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "ok"):
            self.status_code = status_code
            self._payload = payload or {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": len(gateway_peers),
                "peer_capacity": 240,
                "capacity_remaining": 240 - len(gateway_peers),
            }
            self.text = text

        def json(self):
            return self._payload

    class FakeGatewayClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return FakeGatewayResponse()

        def request(self, method, path, *, headers, json=None):
            calls.append((method, path, json))
            if method == "GET" and path == "/v1/peers":
                return FakeGatewayResponse(
                    payload={
                        "interface": "tunnelpilot0",
                        "peers": sorted(gateway_peers.keys()),
                        "peer_allowed_ips": dict(gateway_peers),
                    }
                )
            if method == "POST" and path == "/v1/peers" and json:
                gateway_peers[json["public_key"]] = [json["allowed_ip"]]
                return FakeGatewayResponse()
            if method == "DELETE" and path.startswith("/v1/peers?public_key="):
                from urllib.parse import unquote

                encoded = path.split("public_key=", 1)[1]
                gateway_peers.pop(unquote(encoded), None)
                return FakeGatewayResponse()
            return FakeGatewayResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeGatewayClient)
    admin_headers = {"Authorization": "Bearer secret-admin-token"}

    first = client.post(
        "/v1/devices",
        json=registration(device_id="device-1111", public_key=VALID_PUBLIC_KEY),
        headers=admin_headers,
    )
    second = client.post(
        "/v1/devices",
        json=registration(device_id="device-2222", public_key=second_key),
        headers=admin_headers,
    )
    assert first.status_code == 200
    assert second.status_code == 200

    # Simulate gateway losing device-1111, having an unknown pool peer (stale_key),
    # and having a foreign non-pool peer (foreign_key)
    gateway_peers.clear()
    gateway_peers[second_key] = ["10.67.0.3/32"]
    gateway_peers[stale_key] = ["10.67.0.99/32"]
    gateway_peers[foreign_key] = ["192.168.50.10/32"]

    # 1. Dry-run with prune_unknown=true reports what would happen without touching gateway_peers
    dry = client.post("/v1/servers/reconcile?dry_run=true&prune_unknown=true", headers=admin_headers)
    assert dry.status_code == 200
    dry_report = dry.json()[0]
    assert dry_report["status"] == "dry_run"
    assert dry_report["restored_peers"] == 0
    assert dry_report["removed_peers"] == 0
    assert dry_report["would_restore_peers"] == 1
    assert dry_report["would_remove_peers"] == 1
    assert dry_report["unknown_peers"] == 1
    assert dry_report["unmanaged_peers"] == 1
    assert VALID_PUBLIC_KEY not in gateway_peers
    assert stale_key in gateway_peers

    # 2. Default reconcile (prune_unknown=false) restores missing peer and NEVER deletes unknown peers
    safe_reconcile = client.post("/v1/servers/reconcile", headers=admin_headers)
    assert safe_reconcile.status_code == 200
    safe_report = safe_reconcile.json()[0]
    assert safe_report["status"] == "reconciled"
    assert safe_report["restored_peers"] == 1
    assert safe_report["removed_peers"] == 0
    assert safe_report["unknown_peers"] == 1
    assert safe_report["unmanaged_peers"] == 1
    assert set(gateway_peers.keys()) == {VALID_PUBLIC_KEY, second_key, stale_key, foreign_key}

    # 3. Explicit prune_unknown=true removes only the managed-pool unknown peer (stale_key)
    # and preserves the foreign unmanaged peer (foreign_key)!
    prune_reconcile = client.post("/v1/servers/reconcile?prune_unknown=true", headers=admin_headers)
    assert prune_reconcile.status_code == 200
    prune_report = prune_reconcile.json()[0]
    assert prune_report["restored_peers"] == 0
    assert prune_report["removed_peers"] == 1
    assert prune_report["unmanaged_peers"] == 1
    assert set(gateway_peers.keys()) == {VALID_PUBLIC_KEY, second_key, foreign_key}


def test_reconcile_server_blocks_pruning_against_empty_db_without_confirmation(monkeypatch) -> None:
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    active_key = base64.b64encode(b"\x77" * 32).decode("ascii")
    gateway_peers = {active_key: ["10.67.0.2/32"]}

    class FakeGatewayResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "interface": "tunnelpilot0",
                "peers": list(gateway_peers.keys()),
                "peer_allowed_ips": dict(gateway_peers),
            }

    class FakeGatewayClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, path, *, headers, json=None):
            if method == "DELETE":
                gateway_peers.clear()
            return FakeGatewayResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeGatewayClient)
    admin_headers = {"Authorization": "Bearer secret-admin-token"}

    # DB has 0 devices, but gateway has active_key -> prune_unknown=true is blocked with 409!
    blocked = client.post("/v1/servers/reconcile?prune_unknown=true", headers=admin_headers)
    assert blocked.status_code == 409
    assert active_key in gateway_peers

    # With explicit confirm_empty_db=true, pruning is allowed
    confirmed = client.post(
        "/v1/servers/reconcile?prune_unknown=true&confirm_empty_db=true",
        headers=admin_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()[0]["removed_peers"] == 1
    assert gateway_peers == {}


def test_reconcile_server_aborts_on_foreign_interface_or_corrupt_db(monkeypatch, tmp_path) -> None:
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"
    admin_headers = {"Authorization": "Bearer secret-admin-token"}

    class ForeignIfaceResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {"interface": "wg0", "peers": [VALID_PUBLIC_KEY]}

    class ForeignIfaceClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, path, *, headers, json=None):
            return ForeignIfaceResponse()

    monkeypatch.setattr(main.httpx, "Client", ForeignIfaceClient)

    foreign_resp = client.post("/v1/servers/reconcile", headers=admin_headers)
    assert foreign_resp.status_code == 502
    assert "non-TunnelPilot" in foreign_resp.json()["detail"]

    # Corrupt DB file -> 503 before any gateway call
    main.DEVICE_STORE.path.write_bytes(b"corrupted sqlite bytes")
    corrupt_resp = client.post("/v1/servers/reconcile", headers=admin_headers)
    assert corrupt_resp.status_code == 503
    assert "database" in corrupt_resp.json()["detail"].lower()


def test_reconcile_servers_fail_closed_admin_auth() -> None:
    # 1. When CONTROL_PLANE_TOKEN is None, admin endpoints fail closed with 503
    main.CONTROL_PLANE_TOKEN = None
    unconfigured = client.post("/v1/servers/reconcile")
    assert unconfigured.status_code == 503

    # 2. When CONTROL_PLANE_TOKEN is set, missing or wrong token gets 401
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    unauthorized = client.post("/v1/servers/reconcile")
    wrong_token = client.post(
        "/v1/servers/reconcile",
        headers={"Authorization": "Bearer wrong"},
    )
    authorized = client.post(
        "/v1/servers/reconcile",
        headers={"Authorization": "Bearer secret-admin-token"},
    )

    assert unauthorized.status_code == 401
    assert wrong_token.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()[0]["status"] == "skipped"


def test_reconcile_single_server_not_found_returns_404() -> None:
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    response = client.post(
        "/v1/servers/nonexistent-server/reconcile",
        headers={"Authorization": "Bearer secret-admin-token"},
    )
    assert response.status_code == 404


def test_revoke_device_force_requires_admin_token() -> None:
    created = client.post("/v1/devices", json=registration())
    token = created.json()["device_token"]

    # Device token cannot use force=true
    forbidden = client.delete(
        "/v1/devices/device-1234?force=true",
        headers={"X-Device-Token": token},
    )
    assert forbidden.status_code == 403
    assert main.DEVICE_STORE.get("device-1234") is not None


def test_production_runtime_configuration_rejects_dangerous_defaults() -> None:
    main.ENVIRONMENT = "production"
    main.CONTROL_PLANE_TOKEN = None
    with pytest.raises(RuntimeError, match="TUNNELPILOT_CONTROL_PLANE_TOKEN"):
        main._validate_runtime_configuration()

    main.CONTROL_PLANE_TOKEN = "prod-admin-secret"
    with pytest.raises(RuntimeError, match="Gateway agent URL and token"):
        main._validate_runtime_configuration()

    main.GATEWAY_AGENT_URL = "http://127.0.0.1:8787"
    main.GATEWAY_AGENT_TOKEN = "prod-gw-secret"
    main.SERVERS[0].gateway_api_url = "http://127.0.0.1:8787"
    with pytest.raises(RuntimeError, match="placeholder or empty hostname"):
        main._validate_runtime_configuration()

    main.SERVERS[0].hostname = "vpn.example.com"
    with pytest.raises(RuntimeError, match="invalid WireGuard public key"):
        main._validate_runtime_configuration()

    main.SERVERS[0].public_key = VALID_PUBLIC_KEY
    main._validate_runtime_configuration()


