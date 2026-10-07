from fastapi.testclient import TestClient

from server.app import main


client = TestClient(main.app)


def test_server_catalog_includes_gateway_health(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "status": "ok",
                "wireguard_available": True,
                "peer_count": 4,
                "peer_capacity": 240,
                "capacity_remaining": 236,
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

    monkeypatch.setattr(main.httpx, "Client", FakeClient)
    main.SERVERS[0].enabled = True
    main.SERVERS[0].gateway_api_url = "http://gateway-agent.test"

    try:
        response = client.get("/v1/servers")
        assert response.status_code == 200
        body = response.json()[0]
        assert body["health_status"] == "ok"
        assert body["peer_count"] == 4
        assert body["peer_capacity"] == 240
        assert body["capacity_remaining"] == 236
    finally:
        main.SERVERS[0].gateway_api_url = None
