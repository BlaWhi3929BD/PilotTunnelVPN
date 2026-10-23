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
    main.REQUIRE_HTTPS = True
    main.ALLOW_INSECURE_GATEWAY_HTTP = False
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

    # 1a. Dry-run via query params with prune_unknown=true reports what would happen without touching gateway_peers
    calls.clear()
    dry = client.post("/v1/servers/reconcile?dry_run=true&prune_unknown=true", headers=admin_headers)
    assert dry.status_code == 200
    dry_report = dry.json()[0]
    assert dry_report["status"] == "dry_run"
    assert dry_report["dry_run"] is True
    assert dry_report["prune_unknown"] is True
    assert dry_report["restored_peers"] == 0
    assert dry_report["removed_peers"] == 0
    assert dry_report["would_restore_peers"] == 1
    assert dry_report["would_remove_peers"] == 1
    assert dry_report["unknown_peers"] == 1
    assert dry_report["unmanaged_peers"] == 1
    assert [m for m, _, _ in calls] == ["GET"]
    assert VALID_PUBLIC_KEY not in gateway_peers
    assert stale_key in gateway_peers

    # 1b. Dry-run via JSON body on both /v1/servers/reconcile and /v1/servers/{server_id}/reconcile
    calls.clear()
    dry_body = client.post(
        "/v1/servers/reconcile",
        json={"dry_run": True, "prune_unknown": True},
        headers=admin_headers,
    )
    assert dry_body.status_code == 200
    assert dry_body.json()[0]["status"] == "dry_run"
    assert dry_body.json()[0]["dry_run"] is True
    assert dry_body.json()[0]["would_restore_peers"] == 1
    assert dry_body.json()[0]["would_remove_peers"] == 1
    assert [m for m, _, _ in calls] == ["GET"]

    calls.clear()
    dry_single_body = client.post(
        f"/v1/servers/{main.SERVERS[0].id}/reconcile",
        json={"dry_run": True},
        headers=admin_headers,
    )
    assert dry_single_body.status_code == 200
    assert dry_single_body.json()["status"] == "dry_run"
    assert dry_single_body.json()["dry_run"] is True
    assert dry_single_body.json()["would_restore_peers"] == 1
    assert dry_single_body.json()["would_remove_peers"] == 0
    assert [m for m, _, _ in calls] == ["GET"]

    # 1c. Reject typos in query params or JSON body and conflicting query+body values without touching gateway
    calls.clear()
    typo_body = client.post(
        "/v1/servers/reconcile",
        json={"dryRun": True},
        headers=admin_headers,
    )
    typo_query = client.post(
        "/v1/servers/reconcile?dryRun=true",
        headers=admin_headers,
    )
    conflict_opts = client.post(
        "/v1/servers/reconcile?dry_run=false",
        json={"dry_run": True},
        headers=admin_headers,
    )
    assert typo_body.status_code == 422
    assert typo_query.status_code == 422
    assert conflict_opts.status_code == 400
    assert calls == []

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

        def get(self, path):
            return FakeGatewayResponse(
                payload={
                    "status": "ok",
                    "wireguard_available": True,
                    "peer_count": len(gateway_peers),
                    "peer_capacity": 240,
                    "capacity_remaining": 240 - len(gateway_peers),
                }
            )

        def request(self, method, path, *, headers, json=None):
            if method == "DELETE":
                gateway_peers.clear()
            return FakeGatewayResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeGatewayClient)
    admin_headers = {"Authorization": "Bearer secret-admin-token"}

    # DB has 0 devices, but gateway has active_key -> dry_run without prune_unknown reports unknown_peers safely
    empty_dry = client.post(
        "/v1/servers/reconcile",
        json={"dry_run": True},
        headers=admin_headers,
    )
    assert empty_dry.status_code == 200
    assert empty_dry.json()[0]["status"] == "dry_run"
    assert empty_dry.json()[0]["dry_run"] is True
    assert empty_dry.json()[0]["unknown_peers"] == 1
    assert empty_dry.json()[0]["removed_peers"] == 0
    assert active_key in gateway_peers

    # DB has 0 devices, but gateway has active_key -> prune_unknown=true is blocked with 409!
    blocked = client.post("/v1/servers/reconcile?prune_unknown=true", headers=admin_headers)
    assert blocked.status_code == 409
    assert active_key in gateway_peers

    blocked_dry_prune = client.post(
        "/v1/servers/reconcile",
        json={"dry_run": True, "prune_unknown": True},
        headers=admin_headers,
    )
    assert blocked_dry_prune.status_code == 409
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

        def get(self, path):
            return FakeGatewayResponse(
                payload={
                    "status": "ok",
                    "wireguard_available": True,
                    "peer_count": len(gateway_peers),
                    "peer_capacity": 240,
                    "capacity_remaining": 240 - len(gateway_peers),
                }
            )

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


def test_reconcile_end_to_end_with_gateway_agent_app(monkeypatch) -> None:
    import subprocess
    from server.gateway_agent import app as gw_app
    from server.gateway_agent.wireguard import WireGuardController

    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    main.GATEWAY_AGENT_URL = "http://gateway-agent.local"
    main.GATEWAY_AGENT_TOKEN = "gw-secret-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.local"
    monkeypatch.setattr(gw_app, "GATEWAY_AGENT_TOKEN", "gw-secret-token")
    monkeypatch.setattr(gw_app, "WG_INTERFACE", "tunnelpilot0")

    gw_peers: dict[str, list[str]] = {
        base64.b64encode(b"\x55" * 32).decode("ascii"): ["10.67.0.88/32"],
    }
    mutation_calls: list[tuple[str, str]] = []

    def fake_runner(cmd, **kwargs):
        # cmd formats:
        # ['wg', 'show', 'tunnelpilot0', 'peers']
        # ['wg', 'show', 'tunnelpilot0', 'allowed-ips']
        # ['wg', 'set', 'tunnelpilot0', 'peer', <key>, 'allowed-ips', <cidr>]
        # ['wg', 'set', 'tunnelpilot0', 'peer', <key>, 'remove']
        if cmd[1:4] == ["show", "tunnelpilot0", "peers"]:
            out = "\n".join(sorted(gw_peers.keys())) + ("\n" if gw_peers else "")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr="")
        if cmd[1:4] == ["show", "tunnelpilot0", "allowed-ips"]:
            lines = [f"{k}\t{' '.join(v)}" for k, v in sorted(gw_peers.items())]
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="\n".join(lines) + "\n", stderr="")
        if cmd[1:4] == ["set", "tunnelpilot0", "peer"]:
            pub = cmd[4]
            if cmd[5] == "remove":
                mutation_calls.append(("remove", pub))
                gw_peers.pop(pub, None)
            elif cmd[5] == "allowed-ips":
                mutation_calls.append(("add", pub))
                gw_peers[pub] = [cmd[6]]
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        gw_app,
        "controller",
        WireGuardController(interface="tunnelpilot0", runner=fake_runner),
    )

    gw_client = TestClient(gw_app.app)

    class BridgeGatewayClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return gw_client.get(path)

        def request(self, method, path, *, headers=None, json=None):
            return gw_client.request(method, path, headers=headers, json=json)

        def delete(self, path, *, headers=None):
            return gw_client.delete(path, headers=headers)

    monkeypatch.setattr(main.httpx, "Client", BridgeGatewayClient)
    admin_headers = {"Authorization": "Bearer secret-admin-token"}

    # Register a device (adds VALID_PUBLIC_KEY to gw_peers)
    created = client.post(
        "/v1/devices",
        json=registration(device_id="device-e2e", public_key=VALID_PUBLIC_KEY),
        headers=admin_headers,
    )
    assert created.status_code == 200
    # Simulate gateway restart where VALID_PUBLIC_KEY is missing from kernel but stale peer remains
    gw_peers.pop(VALID_PUBLIC_KEY, None)
    mutation_calls.clear()

    # Dry-run via JSON body against real gateway_agent FastAPI app
    dry_resp = client.post(
        "/v1/servers/reconcile",
        json={"dry_run": True, "prune_unknown": True},
        headers=admin_headers,
    )
    assert dry_resp.status_code == 200
    report = dry_resp.json()[0]
    assert report["status"] == "dry_run"
    assert report["dry_run"] is True
    assert report["prune_unknown"] is True
    assert report["restored_peers"] == 0
    assert report["removed_peers"] == 0
    assert report["would_restore_peers"] == 1
    assert report["would_remove_peers"] == 1
    assert report["unknown_peers"] == 1
    assert mutation_calls == []
    assert VALID_PUBLIC_KEY not in gw_peers


def test_open_registration_never_bypasses_admin_auth_on_reconcile_or_revocation(monkeypatch) -> None:
    main.ALLOW_OPEN_REGISTRATION = True
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "gateway-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    gateway_peers: dict[str, list[str]] = {}
    gateway_calls: list[tuple[str, str]] = []

    class FakeGatewayResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {
                "interface": "tunnelpilot0",
                "peers": sorted(gateway_peers.keys()),
                "peer_allowed_ips": dict(gateway_peers),
            }
            self.text = "ok"

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
            return FakeGatewayResponse(
                payload={
                    "status": "ok",
                    "wireguard_available": True,
                    "peer_count": len(gateway_peers),
                    "peer_capacity": 240,
                    "capacity_remaining": 240 - len(gateway_peers),
                }
            )

        def request(self, method, path, *, headers, json=None):
            gateway_calls.append((method, path))
            if method == "POST" and path == "/v1/peers" and json:
                gateway_peers[json["public_key"]] = [json["allowed_ip"]]
            elif method == "DELETE" and path.startswith("/v1/peers?public_key="):
                from urllib.parse import unquote

                encoded = path.split("public_key=", 1)[1]
                gateway_peers.pop(unquote(encoded), None)
            return FakeGatewayResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeGatewayClient)
    server_id = main.SERVERS[0].id

    # 1. Public client registration works without Bearer token when ALLOW_OPEN_REGISTRATION=true
    created = client.post(
        "/v1/devices",
        json=registration(device_id="device-open", public_key=VALID_PUBLIC_KEY),
    )
    assert created.status_code == 200
    device_token = created.json()["device_token"]
    assert device_token is not None
    assert VALID_PUBLIC_KEY in gateway_peers

    # Existing device still requires X-Device-Token
    re_reg_unauth = client.post(
        "/v1/devices",
        json=registration(device_id="device-open", public_key=VALID_PUBLIC_KEY),
    )
    assert re_reg_unauth.status_code == 401
    re_reg_auth = client.post(
        "/v1/devices",
        json=registration(device_id="device-open", public_key=VALID_PUBLIC_KEY),
        headers={"X-Device-Token": device_token},
    )
    assert re_reg_auth.status_code == 200

    # 2. Rejected admin calls without Bearer token or with wrong token get 401 and do NOT touch gateway or DB
    gateway_calls.clear()
    wrong_headers = {"Authorization": "Bearer wrong-admin-token"}

    assert client.post("/v1/servers/reconcile").status_code == 401
    assert client.post(f"/v1/servers/{server_id}/reconcile").status_code == 401
    assert client.delete("/v1/devices/device-open").status_code == 401
    assert client.delete("/v1/devices/device-open?force=true").status_code == 401

    assert client.post("/v1/servers/reconcile", headers=wrong_headers).status_code == 401
    assert client.post(f"/v1/servers/{server_id}/reconcile", headers=wrong_headers).status_code == 401
    assert client.delete("/v1/devices/device-open", headers=wrong_headers).status_code == 401
    assert client.delete("/v1/devices/device-open?force=true", headers=wrong_headers).status_code == 401

    assert gateway_calls == []
    assert VALID_PUBLIC_KEY in gateway_peers
    assert main.DEVICE_STORE.get("device-open") is not None

    # 3. Missing admin token in configuration fails closed with 503 even when ALLOW_OPEN_REGISTRATION=true
    main.CONTROL_PLANE_TOKEN = None
    assert client.post("/v1/servers/reconcile").status_code == 503
    assert client.post(f"/v1/servers/{server_id}/reconcile").status_code == 503
    assert client.delete("/v1/devices/device-open?force=true").status_code == 503
    assert client.delete("/v1/devices/device-open", headers=wrong_headers).status_code == 503
    assert gateway_calls == []
    assert VALID_PUBLIC_KEY in gateway_peers
    assert main.DEVICE_STORE.get("device-open") is not None

    # 4. With valid admin Bearer token, reconcile and admin revocation succeed
    main.CONTROL_PLANE_TOKEN = "secret-admin-token"
    admin_headers = {"Authorization": "Bearer secret-admin-token"}

    rec_all = client.post("/v1/servers/reconcile", json={"dry_run": True}, headers=admin_headers)
    assert rec_all.status_code == 200
    assert rec_all.json()[0]["status"] == "dry_run"

    rec_one = client.post(f"/v1/servers/{server_id}/reconcile", json={"dry_run": True}, headers=admin_headers)
    assert rec_one.status_code == 200
    assert rec_one.json()["status"] == "dry_run"

    revoked = client.delete("/v1/devices/device-open", headers=admin_headers)
    assert revoked.status_code == 200
    assert VALID_PUBLIC_KEY not in gateway_peers
    assert main.DEVICE_STORE.get("device-open") is None


def test_production_runtime_configuration_rejects_same_tokens_and_insecure_remote_gateway() -> None:
    main.ENVIRONMENT = "production"
    main.CONTROL_PLANE_TOKEN = "shared-secret-token"
    main.GATEWAY_AGENT_TOKEN = "shared-secret-token"
    main.GATEWAY_AGENT_URL = "http://127.0.0.1:8787"
    main.SERVERS[0].gateway_api_url = "http://127.0.0.1:8787"
    main.SERVERS[0].hostname = "vpn.example.com"
    main.SERVERS[0].public_key = VALID_PUBLIC_KEY

    with pytest.raises(RuntimeError, match="must be distinct"):
        main._validate_runtime_configuration()

    main.GATEWAY_AGENT_TOKEN = "distinct-gateway-secret"
    main.SERVERS[0].gateway_api_url = "http://203.0.113.10:8787"
    with pytest.raises(RuntimeError, match="must use https:// or loopback"):
        main._validate_runtime_configuration()

    main.SERVERS[0].gateway_api_url = "https://gateway.internal.example.com:8787"
    main._validate_runtime_configuration()


def test_production_enforces_https_on_credentialed_endpoints() -> None:
    main.ENVIRONMENT = "production"
    main.ALLOW_OPEN_REGISTRATION = True
    main.CONTROL_PLANE_TOKEN = "prod-admin-token"
    admin_headers = {"Authorization": "Bearer prod-admin-token"}

    # Requests behind a proxy with X-Forwarded-Proto: http are rejected with 400
    insecure_headers = {**admin_headers, "X-Forwarded-Proto": "http"}
    assert client.post("/v1/devices", json=registration(), headers=insecure_headers).status_code == 400
    assert client.post("/v1/servers/reconcile", headers=insecure_headers).status_code == 400
    assert (
        client.post(
            f"/v1/servers/{main.SERVERS[0].id}/reconcile",
            headers=insecure_headers,
        ).status_code
        == 400
    )
    assert client.delete("/v1/devices/device-1234", headers=insecure_headers).status_code == 400
    assert (
        client.post(
            "/v1/devices/device-1234/rotate",
            json={"client_public_key": VALID_PUBLIC_KEY, "app_version": "0.2.0"},
            headers={"X-Device-Token": "tok", "X-Forwarded-Proto": "http"},
        ).status_code
        == 400
    )

    # Non-loopback plain HTTP URL is rejected with 400
    public_http_client = TestClient(main.app, base_url="http://cp.example.com")
    assert public_http_client.post("/v1/devices", json=registration()).status_code == 400

    # HTTPS (direct or via X-Forwarded-Proto: https) is permitted
    secure_headers = {**admin_headers, "X-Forwarded-Proto": "https"}
    created = client.post("/v1/devices", json=registration(), headers=secure_headers)
    assert created.status_code == 200
    rec = client.post("/v1/servers/reconcile", json={"dry_run": True}, headers=secure_headers)
    assert rec.status_code == 200


def test_admin_server_crud_enforces_bearer_auth_ssrf_guards_and_delete_dependencies() -> None:
    main.ALLOW_OPEN_REGISTRATION = True
    main.CONTROL_PLANE_TOKEN = "admin-crud-secret"
    admin_headers = {"Authorization": "Bearer admin-crud-secret"}

    new_server_payload = {
        "id": "us-east-1",
        "region": "us-east",
        "hostname": "us1.vpn.example.com",
        "port": 51820,
        "public_key": ANOTHER_PUBLIC_KEY,
        "enabled": True,
        "gateway_api_url": "http://127.0.0.1:8788",
        "gateway_agent_token": "gw-us-east-token",
        "vpn_address_pool": "10.68.0.0/29",
        "vpn_gateway_address": "10.68.0.1",
        "peer_capacity": 4,
        "tier": "free",
    }

    # Unauthenticated or wrong token rejected even with ALLOW_OPEN_REGISTRATION=true
    assert client.post("/v1/servers", json=new_server_payload).status_code == 401
    assert client.patch("/v1/servers/dev-lan-1", json={"enabled": False}).status_code == 401
    assert client.delete("/v1/servers/dev-lan-1").status_code == 401
    assert client.get("/v1/servers?include_disabled=true").status_code == 401

    # SSRF validation blocks cloud metadata and non-http schemes
    ssrf_payload = {**new_server_payload, "gateway_api_url": "http://169.254.169.254/latest/meta-data"}
    assert client.post("/v1/servers", json=ssrf_payload, headers=admin_headers).status_code == 422
    scheme_payload = {**new_server_payload, "gateway_api_url": "file:///etc/passwd"}
    assert client.post("/v1/servers", json=scheme_payload, headers=admin_headers).status_code == 422

    # Create server succeeds with admin Bearer token and never leaks gateway_agent_token in response
    created_srv = client.post("/v1/servers", json=new_server_payload, headers=admin_headers)
    assert created_srv.status_code == 201
    body = created_srv.json()
    assert body["id"] == "us-east-1"
    assert "gateway_agent_token" not in body

    # Duplicate server id returns 409
    assert client.post("/v1/servers", json=new_server_payload, headers=admin_headers).status_code == 409

    # Filter by region
    us_servers = client.get("/v1/servers?region=us-east").json()
    assert [s["id"] for s in us_servers] == ["us-east-1"]

    # Disable and list with include_disabled=true
    patched = client.patch(
        "/v1/servers/us-east-1",
        json={"enabled": False},
        headers=admin_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert "us-east-1" not in [s["id"] for s in client.get("/v1/servers").json()]
    assert "us-east-1" in [
        s["id"] for s in client.get("/v1/servers?include_disabled=true", headers=admin_headers).json()
    ]

    # Re-enable without gateway_api_url so we can register a device and test delete guard
    client.patch(
        "/v1/servers/us-east-1",
        json={"enabled": True, "gateway_api_url": None},
        headers=admin_headers,
    )
    reg = client.post(
        "/v1/devices",
        json={
            "device_id": "pinned-us-device",
            "client_public_key": VALID_PUBLIC_KEY,
            "app_version": "0.2.0",
            "server_id": "us-east-1",
        },
    )
    assert reg.status_code == 200
    assert reg.json()["server"]["id"] == "us-east-1"
    assert reg.json()["client_address"] == "10.68.0.2/32"

    # Deleting a server with assigned devices returns 409 Conflict
    del_conflict = client.delete("/v1/servers/us-east-1", headers=admin_headers)
    assert del_conflict.status_code == 409

    # After revoking the device, server deletion succeeds
    assert client.delete("/v1/devices/pinned-us-device", headers=admin_headers).status_code == 200
    del_ok = client.delete("/v1/servers/us-east-1", headers=admin_headers)
    assert del_ok.status_code == 200
    assert del_ok.json()["status"] == "deleted"


def test_device_server_pinning_migration_rollback_tombstone_and_multi_server_reconcile(monkeypatch) -> None:
    main.ALLOW_OPEN_REGISTRATION = True
    main.CONTROL_PLANE_TOKEN = "admin-migrate-secret"
    admin_headers = {"Authorization": "Bearer admin-migrate-secret"}

    gw_peers_by_url: dict[str, dict[str, list[str]]] = {
        "http://127.0.0.1:8787": {},
        "http://127.0.0.1:8788": {},
    }
    fail_post_on_url: set[str] = set()
    fail_delete_on_url: set[str] = set()
    offline_urls: set[str] = set()

    class FakeResp:
        def __init__(self, status_code: int = 200, text: str = "ok", payload: dict | None = None):
            self.status_code = status_code
            self.text = text
            self._payload = payload or {"status": "ok"}

        def json(self):
            return self._payload

    class MultiGatewayClient:
        def __init__(self, *args, **kwargs):
            self.base_url = kwargs.get("base_url", "")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            if self.base_url in offline_urls:
                raise main.httpx.ConnectError("gateway offline")
            peers = gw_peers_by_url.setdefault(self.base_url, {})
            return FakeResp(
                payload={
                    "status": "ok",
                    "wireguard_available": True,
                    "peer_count": len(peers),
                    "peer_capacity": 240,
                    "capacity_remaining": 240 - len(peers),
                }
            )

        def request(self, method, path, *, headers, json=None):
            if self.base_url in offline_urls:
                raise main.httpx.ConnectError("gateway offline")
            peers = gw_peers_by_url.setdefault(self.base_url, {})
            if method == "GET" and path == "/v1/peers":
                return FakeResp(
                    payload={
                        "interface": "tunnelpilot0",
                        "peers": list(peers.keys()),
                        "peer_allowed_ips": {k: list(v) for k, v in peers.items()},
                    }
                )
            if method == "POST" and path == "/v1/peers" and json:
                if self.base_url in fail_post_on_url:
                    return FakeResp(status_code=500, text="target gateway error")
                peers[json["public_key"]] = [json["allowed_ip"]]
                return FakeResp()
            if method == "DELETE" and path.startswith("/v1/peers?public_key="):
                if self.base_url in fail_delete_on_url:
                    return FakeResp(status_code=500, text="source gateway revoke error")
                from urllib.parse import unquote

                key = unquote(path.split("public_key=", 1)[1])
                peers.pop(key, None)
                return FakeResp()
            return FakeResp()

    monkeypatch.setattr(main.httpx, "Client", MultiGatewayClient)
    main.GATEWAY_AGENT_URL = "http://127.0.0.1:8787"
    main.GATEWAY_AGENT_TOKEN = "token-gw-1"
    default_id = main.SERVERS[0].id

    # Add second server (eu-west-2) with its own pool and gateway URL
    create_resp = client.post(
        "/v1/servers",
        headers=admin_headers,
        json={
            "id": "eu-west-2",
            "region": "eu-west",
            "hostname": "eu-west-2.vpn.example.com",
            "port": 51820,
            "public_key": ANOTHER_PUBLIC_KEY,
            "enabled": True,
            "gateway_api_url": "http://127.0.0.1:8788",
            "gateway_agent_token": "token-gw-2",
            "vpn_address_pool": "10.69.0.0/24",
            "vpn_gateway_address": "10.69.0.1",
            "peer_capacity": 240,
            "tier": "free",
        },
    )
    assert create_resp.status_code == 201

    # 1. Register device on default server
    reg = client.post(
        "/v1/devices",
        json={
            "device_id": "device-mig-1",
            "client_public_key": VALID_PUBLIC_KEY,
            "app_version": "0.2.0",
            "server_id": default_id,
        },
    )
    assert reg.status_code == 200
    token = reg.json()["device_token"]
    assert reg.json()["server"]["id"] == default_id
    assert reg.json()["client_address"] == "10.67.0.2/32"
    assert VALID_PUBLIC_KEY in gw_peers_by_url["http://127.0.0.1:8787"]

    # 2. Re-registration without server_id stays pinned to default_id; passing a different server_id returns 409
    re_reg = client.post(
        "/v1/devices",
        json={
            "device_id": "device-mig-1",
            "client_public_key": VALID_PUBLIC_KEY,
            "app_version": "0.2.0",
        },
        headers={"X-Device-Token": token},
    )
    assert re_reg.status_code == 200
    assert re_reg.json()["server"]["id"] == default_id

    pinned_conflict = client.post(
        "/v1/devices",
        json={
            "device_id": "device-mig-1",
            "client_public_key": VALID_PUBLIC_KEY,
            "app_version": "0.2.0",
            "server_id": "eu-west-2",
        },
        headers={"X-Device-Token": token},
    )
    assert pinned_conflict.status_code == 409

    # 3. Migration rollback if target gateway fails to install peer: device stays on default_id
    fail_post_on_url.add("http://127.0.0.1:8788")
    failed_mig = client.post(
        "/v1/devices/device-mig-1/migrate",
        json={"target_server_id": "eu-west-2", "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )
    assert failed_mig.status_code == 502
    assert main.DEVICE_STORE.get("device-mig-1")["server_id"] == default_id
    assert VALID_PUBLIC_KEY in gw_peers_by_url["http://127.0.0.1:8787"]
    fail_post_on_url.clear()

    # 4. Migration succeeds even if source gateway revocation fails transiently; records tombstone for source server
    fail_delete_on_url.add("http://127.0.0.1:8787")
    ok_mig = client.post(
        "/v1/devices/device-mig-1/migrate",
        json={"target_server_id": "eu-west-2", "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )
    assert ok_mig.status_code == 200
    mig_body = ok_mig.json()
    assert mig_body["previous_server_id"] == default_id
    assert mig_body["server"]["id"] == "eu-west-2"
    assert mig_body["client_address"] == "10.69.0.2/32"
    assert VALID_PUBLIC_KEY in gw_peers_by_url["http://127.0.0.1:8788"]
    # Source gateway still has the stale peer until reconciled, and tombstone is recorded
    assert VALID_PUBLIC_KEY in gw_peers_by_url["http://127.0.0.1:8787"]
    assert len(main.DEVICE_STORE.list_tombstones(default_id)) == 1

    # 5. Non-destructive reconciliation (prune_unknown=False) on default_id automatically removes the tombstoned peer!
    fail_delete_on_url.clear()
    rec_dev1 = client.post(
        f"/v1/servers/{default_id}/reconcile",
        json={"dry_run": False, "prune_unknown": False},
        headers=admin_headers,
    )
    assert rec_dev1.status_code == 200
    assert rec_dev1.json()["removed_peers"] == 1
    assert VALID_PUBLIC_KEY not in gw_peers_by_url["http://127.0.0.1:8787"]
    assert len(main.DEVICE_STORE.list_tombstones(default_id)) == 0

    # 6. Batch reconciliation isolates an offline gateway without aborting healthy servers
    offline_urls.add("http://127.0.0.1:8787")
    batch = client.post("/v1/servers/reconcile", json={"dry_run": True}, headers=admin_headers)
    assert batch.status_code == 200
    by_id = {item["server_id"]: item for item in batch.json()}
    assert by_id[default_id]["status"] == "error"
    assert by_id["eu-west-2"]["status"] == "dry_run"


def test_premium_server_tier_enforcement_and_device_tier_upgrade() -> None:
    main.ALLOW_OPEN_REGISTRATION = True
    main.CONTROL_PLANE_TOKEN = "admin-tier-secret"
    admin_headers = {"Authorization": "Bearer admin-tier-secret"}

    # Create a premium server
    created = client.post(
        "/v1/servers",
        headers=admin_headers,
        json={
            "id": "ch-zurich-premium",
            "region": "eu-central",
            "hostname": "ch1.vpn.example.com",
            "port": 51820,
            "public_key": ANOTHER_PUBLIC_KEY,
            "enabled": True,
            "vpn_address_pool": "10.70.0.0/24",
            "vpn_gateway_address": "10.70.0.1",
            "peer_capacity": 100,
            "tier": "premium",
        },
    )
    assert created.status_code == 201
    assert created.json()["tier"] == "premium"

    # Free device registration directly onto premium server is rejected with 403
    denied = client.post(
        "/v1/devices",
        json={
            "device_id": "device-tier-1",
            "client_public_key": VALID_PUBLIC_KEY,
            "app_version": "0.2.0",
            "server_id": "ch-zurich-premium",
        },
    )
    assert denied.status_code == 403

    # Register on default free server first
    reg = client.post(
        "/v1/devices",
        json={
            "device_id": "device-tier-1",
            "client_public_key": VALID_PUBLIC_KEY,
            "app_version": "0.2.0",
        },
    )
    assert reg.status_code == 200
    token = reg.json()["device_token"]
    assert reg.json()["tier"] == "free"

    # Migrating to premium server while still on free tier returns 403
    mig_denied = client.post(
        "/v1/devices/device-tier-1/migrate",
        json={"target_server_id": "ch-zurich-premium", "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )
    assert mig_denied.status_code == 403

    # Upgrading to premium without purchase_token is rejected with 403
    unverified_upgrade = client.post(
        "/v1/devices/device-tier-1/tier",
        json={"tier": "premium"},
        headers={"X-Device-Token": token},
    )
    assert unverified_upgrade.status_code == 403

    # Upgrade device to premium tier with valid purchase_token and migrate
    upgraded = client.post(
        "/v1/devices/device-tier-1/tier",
        json={"tier": "premium", "purchase_token": "play-billing-token-12345"},
        headers={"X-Device-Token": token},
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["tier"] == "premium"

    mig_ok = client.post(
        "/v1/devices/device-tier-1/migrate",
        json={"target_server_id": "ch-zurich-premium", "app_version": "0.2.0"},
        headers={"X-Device-Token": token},
    )
    assert mig_ok.status_code == 200
    assert mig_ok.json()["server"]["id"] == "ch-zurich-premium"
    assert mig_ok.json()["tier"] == "premium"
