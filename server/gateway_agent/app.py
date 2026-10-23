from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Query, status

from .models import GatewayHealthResponse, PeerCreateRequest, PeerListResponse, PeerResponse
from .wireguard import WireGuardController

ENVIRONMENT = os.getenv("TUNNELPILOT_ENV", "development").strip().lower()
GATEWAY_AGENT_TOKEN = os.getenv("TUNNELPILOT_GATEWAY_AGENT_TOKEN")
WG_INTERFACE = os.getenv("TUNNELPILOT_WG_INTERFACE", "tunnelpilot0")
WG_BINARY = os.getenv("TUNNELPILOT_WG_BINARY", "wg")
WG_MAX_PEERS = max(1, int(os.getenv("TUNNELPILOT_WG_MAX_PEERS", "240")))
ALLOW_NONSTANDARD_WG_INTERFACE = os.getenv(
    "TUNNELPILOT_ALLOW_NONSTANDARD_WG_INTERFACE", "false"
).lower() in {"1", "true", "yes", "on"}

controller = WireGuardController(
    interface=WG_INTERFACE,
    binary=WG_BINARY,
    allow_nonstandard_interface=ALLOW_NONSTANDARD_WG_INTERFACE,
)


def _validate_gateway_configuration() -> None:
    controller.ensure_managed_interface()
    if ENVIRONMENT == "production":
        if not GATEWAY_AGENT_TOKEN or not GATEWAY_AGENT_TOKEN.strip():
            raise RuntimeError("TUNNELPILOT_GATEWAY_AGENT_TOKEN must be configured in production")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    _validate_gateway_configuration()
    yield


app = FastAPI(title="TunnelPilot Gateway Agent", version="0.2.0", lifespan=_lifespan)


def _require_auth(authorization: str | None) -> None:
    if not GATEWAY_AGENT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gateway agent token is not configured",
        )
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {GATEWAY_AGENT_TOKEN}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.get("/healthz", response_model=GatewayHealthResponse)
def healthz() -> GatewayHealthResponse:
    try:
        controller.ensure_managed_interface()
        controller.ensure_available()
        peer_count = controller.peer_count()
    except (RuntimeError, ValueError):
        return GatewayHealthResponse(
            status="degraded",
            interface=WG_INTERFACE,
            wireguard_available=False,
            peer_count=0,
            peer_capacity=WG_MAX_PEERS,
            capacity_remaining=0,
        )

    capacity_remaining = max(0, WG_MAX_PEERS - peer_count)
    return GatewayHealthResponse(
        status="full" if capacity_remaining == 0 else "ok",
        interface=WG_INTERFACE,
        wireguard_available=True,
        peer_count=peer_count,
        peer_capacity=WG_MAX_PEERS,
        capacity_remaining=capacity_remaining,
    )


@app.get("/v1/peers", response_model=PeerListResponse)
def list_peers(
    authorization: str | None = Header(default=None),
) -> PeerListResponse:
    _require_auth(authorization)
    try:
        controller.ensure_managed_interface()
        peers = controller.list_peers()
        try:
            peer_allowed_ips = controller.list_peer_allowed_ips()
        except Exception:
            peer_allowed_ips = {}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PeerListResponse(
        interface=WG_INTERFACE,
        peers=peers,
        peer_allowed_ips=peer_allowed_ips,
    )


@app.post("/v1/peers", response_model=PeerResponse)
def add_peer(
    request: PeerCreateRequest,
    authorization: str | None = Header(default=None),
) -> PeerResponse:
    _require_auth(authorization)
    try:
        controller.add_peer(request.public_key, request.allowed_ip)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PeerResponse(
        status="provisioned",
        public_key=request.public_key,
        allowed_ip=request.allowed_ip,
    )


@app.delete("/v1/peers")
def remove_peer(
    public_key: str = Query(min_length=40, max_length=64),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    _require_auth(authorization)
    try:
        controller.remove_peer(public_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"status": "revoked", "public_key": public_key}
