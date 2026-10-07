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
    main.SERVERS[0].enabled = True


def registration(
    device_id: str = "device-1234",
    public_key: str = VALID_PUBLIC_KEY,
) -> dict[str, str]:
    return {
        "device_id": device_id,
        "client_public_key": public_key,
        "app_version": "0.1.0",
    }


def test_registers_device_and_assigns_server() -> None:
    response = client.post("/v1/devices", json=registration())

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "accepted"
    assert body["device_id"] == "device-1234"
    assert body["server"]["id"] == "dev-1"
    assert body["registered_at"]
    assert main.DEVICES["device-1234"].client_public_key == VALID_PUBLIC_KEY


def test_reregistration_with_same_key_is_allowed() -> None:
    first = client.post("/v1/devices", json=registration())
    second = client.post("/v1/devices", json=registration())

    assert first.status_code == 200
    assert second.status_code == 200
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
