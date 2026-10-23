import subprocess

from server.gateway_agent import app as gateway_app
from server.gateway_agent.wireguard import WireGuardController


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

    response = gateway_app.list_peers(authorization="Bearer secret-gw-token")

    assert response.interface == gateway_app.WG_INTERFACE
    assert response.peers == ["peer-a", "peer-b"]

