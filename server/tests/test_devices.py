import base64

import pytest
from fastapi.testclient import TestClient

from server.app import main


client = TestClient(main.app)

VALID_PUBLIC_KEY = base64.b64encode(bytes(range(32))).decode()
ANOTHER_PUBLIC_KEY = base64.b64encode(bytes(range(32, 64))).decode()


@pytest.fixture(autouse=True)
def reset_devices() -> None:
    main.DEVICES.clear()
    main.CONTROL_PLANE_TOKEN = None
    main.GATEWAY_AGENT_URL = None
    main.GATEWAY_AGENT_TOKEN = None
    main.VPN_ADDRESS_POOL = "10.67.0.0/24"
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
    assert body["device_id"] == "device-1234"
    assert body["server"]["id"] == "dev-1"
    assert body["client_address"] == "10.67.0.2/32"
    assert body["provisioned"] is False
    assert body["registered_at"]
    assert main.DEVICES["device-1234"].client_public_key == VALID_PUBLIC_KEY


def test_reregistration_with_same_key_is_allowed_and_reuses_address() -> None:
    first = client.post("/v1/devices", json=registration())
    second = client.post("/v1/devices", json=registration())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["client_address"] == second.json()["client_address"]
    assert len(main.DEVICES) == 1


def test_device_id_with_different_key_is_rejected() -> None:
    first = client.post("/v1/devices", json=registration())
    second = client.post(
        "/v1/devices",
        json=registration(public_key=ANOTHER_PUBLIC_KEY),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "different public key" in second.json()["detail"]


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
    response = client.post(
        "/v1/devices",
        json=registration(public_key=public_key),
    )

    assert response.status_code == 422


def test_missing_server_returns_503() -> None:
    main.SERVERS[0].enabled = False

    response = client.post("/v1/devices", json=registration())

    assert response.status_code == 503
    assert response.json()["detail"] == "No VPN server is currently available"


def test_control_plane_token_can_be_required() -> None:
    main.CONTROL_PLANE_TOKEN = "test-token"

    unauthorized = client.post(
        "/v1/devices",
        json=registration(),
    )
    authorized = client.post(
        "/v1/devices",
        json=registration(),
        headers={"Authorization": "Bearer test-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_registration_provisions_peer_when_gateway_agent_is_configured(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "test-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    calls: list[tuple[str, str, dict[str, str] | None, dict[str, str]]] = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, path, *, headers, json=None):
            calls.append((method, path, json, headers))
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    response = client.post("/v1/devices", json=registration())

    assert response.status_code == 200
    assert response.json()["provisioned"] is True
    assert calls == [
        (
            "POST",
            "/v1/peers",
            {"public_key": VALID_PUBLIC_KEY, "allowed_ip": "10.67.0.2/32"},
            {"Authorization": "Bearer test-token"},
        )
    ]


def test_revoke_device_removes_provisioned_peer(monkeypatch) -> None:
    main.GATEWAY_AGENT_URL = "http://gateway-agent.test"
    main.GATEWAY_AGENT_TOKEN = "test-token"
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    calls: list[tuple[str, str]] = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, path, *, headers, json=None):
            calls.append((method, path))
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    created = client.post("/v1/devices", json=registration())
    assert created.status_code == 200

    revoked = client.delete("/v1/devices/device-1234")

    assert revoked.status_code == 200
    assert revoked.json() == {"status": "revoked", "device_id": "device-1234"}
    assert "device-1234" not in main.DEVICES
    assert calls == [
        ("POST", "/v1/peers"),
        ("DELETE", f"/v1/peers?public_key={VALID_PUBLIC_KEY[:-1]}%3D"),
    ]


