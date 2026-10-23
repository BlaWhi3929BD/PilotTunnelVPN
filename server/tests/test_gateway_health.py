import subprocess

import pytest
from fastapi import HTTPException

from server.gateway_agent import app as gateway_app
from server.gateway_agent.wireguard import WireGuardController, validate_interface_name


def test_peer_count_uses_wireguard_peers_output() -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="peer-one\npeer-two\n",
            stderr="",
        )

    controller = WireGuardController(runner=runner)

    assert controller.peer_count() == 2


def test_healthz_reports_capacity(monkeypatch) -> None:
    monkeypatch.setattr(WireGuardController, "ensure_available", lambda self: None)
    monkeypatch.setattr(WireGuardController, "peer_count", lambda self: 3)
    monkeypatch.setattr(gateway_app, "WG_MAX_PEERS", 10)

    response = gateway_app.healthz()

    assert response.status == "ok"
    assert response.wireguard_available is True
    assert response.peer_count == 3
    assert response.peer_capacity == 10
    assert response.capacity_remaining == 7


def test_healthz_reports_degraded_when_wireguard_is_unavailable(monkeypatch) -> None:
    def fail() -> None:
        raise RuntimeError("wg is down")

    monkeypatch.setattr(WireGuardController, "ensure_available", lambda self: fail())
    monkeypatch.setattr(gateway_app, "WG_MAX_PEERS", 10)

    response = gateway_app.healthz()

    assert response.status == "degraded"
    assert response.wireguard_available is False
    assert response.capacity_remaining == 0


def test_list_peers_returns_trimmed_peer_keys() -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="peer-one\n\n peer-two \n",
            stderr="",
        )

    controller = WireGuardController(runner=runner)

    assert controller.list_peers() == ["peer-one", "peer-two"]


def test_gateway_list_peers_endpoint_returns_active_peers(monkeypatch) -> None:
    monkeypatch.setattr(gateway_app, "GATEWAY_AGENT_TOKEN", "secret-gw-token")
    monkeypatch.setattr(WireGuardController, "list_peers", lambda self: ["peer-a", "peer-b"])
    monkeypatch.setattr(
        WireGuardController,
        "list_peer_allowed_ips",
        lambda self: {"peer-a": ["10.67.0.2/32"], "peer-b": ["10.67.0.3/32"]},
    )

    response = gateway_app.list_peers(authorization="Bearer secret-gw-token")

    assert response.interface == gateway_app.WG_INTERFACE
    assert response.peers == ["peer-a", "peer-b"]
    assert response.peer_allowed_ips == {"peer-a": ["10.67.0.2/32"], "peer-b": ["10.67.0.3/32"]}


def test_list_peer_allowed_ips_parses_wg_output() -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="peer-one\t10.67.0.2/32\npeer-two\t(none)\npeer-three\t10.67.0.4/32 192.168.10.0/24\n",
            stderr="",
        )

    controller = WireGuardController(runner=runner)
    assert controller.list_peer_allowed_ips() == {
        "peer-one": ["10.67.0.2/32"],
        "peer-two": [],
        "peer-three": ["10.67.0.4/32", "192.168.10.0/24"],
    }


def test_validate_interface_name_blocks_foreign_interfaces() -> None:
    assert validate_interface_name("tunnelpilot0") == "tunnelpilot0"
    with pytest.raises(ValueError, match="non-TunnelPilot"):
        validate_interface_name("wg0")
    assert validate_interface_name("wg0", allow_nonstandard=True) == "wg0"


def test_gateway_auth_rejects_missing_or_wrong_token(monkeypatch) -> None:
    monkeypatch.setattr(gateway_app, "GATEWAY_AGENT_TOKEN", "secret-gw-token")
    with pytest.raises(HTTPException) as exc_info:
        gateway_app.list_peers(authorization=None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_wrong:
        gateway_app.list_peers(authorization="Bearer wrong-token")
    assert exc_wrong.value.status_code == 401


def test_gateway_startup_validation_enforces_managed_interface_and_production_token(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_app,
        "controller",
        WireGuardController(interface="wg0", allow_nonstandard_interface=False),
    )
    with pytest.raises(ValueError, match="non-TunnelPilot"):
        gateway_app._validate_gateway_configuration()

    monkeypatch.setattr(
        gateway_app,
        "controller",
        WireGuardController(interface="tunnelpilot0", allow_nonstandard_interface=False),
    )
    monkeypatch.setattr(gateway_app, "ENVIRONMENT", "production")
    monkeypatch.setattr(gateway_app, "GATEWAY_AGENT_TOKEN", None)
    with pytest.raises(RuntimeError, match="TUNNELPILOT_GATEWAY_AGENT_TOKEN"):
        gateway_app._validate_gateway_configuration()

    monkeypatch.setattr(gateway_app, "GATEWAY_AGENT_TOKEN", "prod-gateway-token")
    gateway_app._validate_gateway_configuration()
