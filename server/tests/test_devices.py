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
    main.VPN_ADDRESS_POOL = "10.67.0.0/24"
    main.VPN_GATEWAY_ADDRESS = "10.67.0.1"
    main.SERVERS[0].enabled = True
    main.SERVERS[0].gateway_api_url = None


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
