from __future__ import annotations

import base64
import binascii
import ipaddress
import os
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="TunnelPilot Control Plane", version="0.4.0")

CONTROL_PLANE_TOKEN = os.getenv("TUNNELPILOT_CONTROL_PLANE_TOKEN")
GATEWAY_AGENT_URL = os.getenv("TUNNELPILOT_GATEWAY_AGENT_URL")
GATEWAY_AGENT_TOKEN = os.getenv("TUNNELPILOT_GATEWAY_AGENT_TOKEN")
VPN_ADDRESS_POOL = os.getenv("TUNNELPILOT_VPN_ADDRESS_POOL", "10.67.0.0/24")
VPN_GATEWAY_ADDRESS = os.getenv("TUNNELPILOT_VPN_GATEWAY_ADDRESS", "10.67.0.1")
SERVER_ID = os.getenv("TUNNELPILOT_SERVER_ID", "dev-1")
SERVER_REGION = os.getenv("TUNNELPILOT_SERVER_REGION", "dev")
SERVER_HOSTNAME = os.getenv("TUNNELPILOT_SERVER_HOSTNAME", "replace-with-real-gateway")
SERVER_PUBLIC_KEY = os.getenv("TUNNELPILOT_SERVER_PUBLIC_KEY", "replace-with-gateway-public-key")
SERVER_PORT = int(os.getenv("TUNNELPILOT_SERVER_PORT", "51820"))
SERVER_ENABLED = os.getenv("TUNNELPILOT_SERVER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
GATEWAY_HEALTH_TIMEOUT = float(os.getenv("TUNNELPILOT_GATEWAY_HEALTH_TIMEOUT", "3.0"))


class Server(BaseModel):
    id: str
    region: str
    hostname: str
    public_key: str
    port: int = Field(default=51820, ge=1, le=65535)
    enabled: bool = True
    gateway_api_url: str | None = Field(default=None, exclude=True)
    health_status: str = "unknown"
    peer_count: int | None = None
    peer_capacity: int | None = None
    capacity_remaining: int | None = None


class DeviceRegistration(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    client_public_key: str
    app_version: str = Field(min_length=1, max_length=32)

    @field_validator("client_public_key")
    @classmethod
    def validate_client_public_key(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("client_public_key must be standard base64") from exc
        if len(decoded) != 32:
            raise ValueError("client_public_key must decode to exactly 32 bytes")
        return value


class DeviceRecord(BaseModel):
    device_id: str
    client_public_key: str
    app_version: str
    server_id: str
    client_address: str
    created_at: datetime
    last_seen_at: datetime
    provisioned: bool = False


class DeviceRegistrationResponse(BaseModel):
    status: str
    device_id: str
    server: Server
    client_address: str
    provisioned: bool
    registered_at: datetime


class DeviceRevocationResponse(BaseModel):
    status: str
    device_id: str


SERVERS = [
    Server(
        id=SERVER_ID,
        region=SERVER_REGION,
        hostname=SERVER_HOSTNAME,
        public_key=SERVER_PUBLIC_KEY,
        port=SERVER_PORT,
        enabled=SERVER_ENABLED,
        gateway_api_url=GATEWAY_AGENT_URL,
    )
]

# Development-only in-memory registry. Production must use durable storage.
DEVICES: dict[str, DeviceRecord] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_control_plane_auth(authorization: str | None) -> None:
    if CONTROL_PLANE_TOKEN is not None and authorization != f"Bearer {CONTROL_PLANE_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _address_pool() -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(VPN_ADDRESS_POOL, strict=True)
    except ValueError as exc:
        raise RuntimeError("TUNNELPILOT_VPN_ADDRESS_POOL must be a valid CIDR network") from exc
    if network.version != 4 or network.prefixlen >= 31:
        raise RuntimeError("TUNNELPILOT_VPN_ADDRESS_POOL must be an IPv4 network of at least /30")
    return network


def _allocate_client_address() -> str:
    network = _address_pool()
    used = {record.client_address.split("/", 1)[0] for record in DEVICES.values()}
    try:
        gateway_address = ipaddress.ip_address(VPN_GATEWAY_ADDRESS)
    except ValueError as exc:
        raise RuntimeError("TUNNELPILOT_VPN_GATEWAY_ADDRESS must be a valid IPv4 address") from exc
    if gateway_address.version != 4 or gateway_address not in network:
        raise RuntimeError("TUNNELPILOT_VPN_GATEWAY_ADDRESS must be inside TUNNELPILOT_VPN_ADDRESS_POOL")

    for host in network.hosts():
        value = str(host)
        if host == gateway_address:
            continue
        if value not in used:
            return f"{value}/32"
    raise HTTPException(status_code=503, detail="No VPN client addresses are currently available")


def _gateway_url(server: Server) -> str | None:
    return server.gateway_api_url or GATEWAY_AGENT_URL


def _gateway_headers() -> dict[str, str]:
    if not GATEWAY_AGENT_TOKEN:
        raise HTTPException(status_code=503, detail="Gateway agent token is not configured")
    return {"Authorization": f"Bearer {GATEWAY_AGENT_TOKEN}"}


def _gateway_request(
    method: str,
    path: str,
    *,
    server: Server,
    json: dict[str, str] | None = None,
) -> httpx.Response:
    base_url = _gateway_url(server)
    if not base_url:
        raise HTTPException(status_code=503, detail="Gateway agent URL is not configured")

    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0) as client:
            return client.request(method, path, headers=_gateway_headers(), json=json)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Gateway agent is unreachable") from exc


def _probe_gateway(server: Server) -> dict[str, int | str | bool]:
    base_url = _gateway_url(server)
    if not base_url:
        return {
            "status": "unconfigured",
            "wireguard_available": False,
            "peer_count": 0,
            "peer_capacity": 0,
            "capacity_remaining": 0,
        }

    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=GATEWAY_HEALTH_TIMEOUT) as client:
            response = client.get("/healthz")
    except httpx.HTTPError:
        return {
            "status": "unreachable",
            "wireguard_available": False,
            "peer_count": 0,
            "peer_capacity": 0,
            "capacity_remaining": 0,
        }

    if response.status_code >= 300:
        return {
            "status": "degraded",
            "wireguard_available": False,
            "peer_count": 0,
            "peer_capacity": 0,
            "capacity_remaining": 0,
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "status": "degraded",
            "wireguard_available": False,
            "peer_count": 0,
            "peer_capacity": 0,
            "capacity_remaining": 0,
        }

    peer_count = int(payload.get("peer_count", 0))
    peer_capacity = int(payload.get("peer_capacity", 0))
    remaining = max(0, int(payload.get("capacity_remaining", peer_capacity - peer_count)))
    wireguard_available = bool(payload.get("wireguard_available", False))
    health_status = str(payload.get("status", "degraded"))
    if not wireguard_available:
        health_status = "degraded"

    return {
        "status": health_status,
        "wireguard_available": wireguard_available,
        "peer_count": peer_count,
        "peer_capacity": peer_capacity,
        "capacity_remaining": remaining,
    }


def _server_with_health(server: Server) -> Server:
    health = _probe_gateway(server)
    return server.model_copy(
        update={
            "health_status": health["status"],
            "peer_count": health["peer_count"],
            "peer_capacity": health["peer_capacity"],
            "capacity_remaining": health["capacity_remaining"],
        }
    )


def _provision_peer(server: Server, public_key: str, client_address: str) -> None:
    response = _gateway_request(
        "POST",
        "/v1/peers",
        server=server,
        json={"public_key": public_key, "allowed_ip": client_address},
    )
    if response.status_code >= 300:
        detail = response.text[:300] or "Gateway agent rejected peer provisioning"
        raise HTTPException(status_code=502, detail=detail)


def _revoke_peer(server: Server, public_key: str) -> None:
    response = _gateway_request(
        "DELETE",
        f"/v1/peers?public_key={quote(public_key, safe='')}",
        server=server,
    )
    if response.status_code >= 300:
        detail = response.text[:300] or "Gateway agent rejected peer revocation"
        raise HTTPException(status_code=502, detail=detail)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/servers", response_model=list[Server])
def list_servers() -> list[Server]:
    enabled = [server for server in SERVERS if server.enabled]
    healthy = [_server_with_health(server) for server in enabled]
    return sorted(
        healthy,
        key=lambda server: (
            server.health_status not in {"ok", "full"},
            -(server.capacity_remaining or 0),
            server.id,
        ),
    )


@app.post("/v1/devices", response_model=DeviceRegistrationResponse)
def register_device(
    registration: DeviceRegistration,
    authorization: Annotated[str | None, Header()] = None,
) -> DeviceRegistrationResponse:
    _require_control_plane_auth(authorization)

    server = next((item for item in SERVERS if item.enabled), None)
    if server is None:
        raise HTTPException(status_code=503, detail="No VPN server is currently available")

    existing = DEVICES.get(registration.device_id)
    if existing is not None and existing.client_public_key != registration.client_public_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="device_id is already registered with a different public key",
        )

    same_key = next(
        (
            item
            for item in DEVICES.values()
            if item.client_public_key == registration.client_public_key
            and item.device_id != registration.device_id
        ),
        None,
    )
    if same_key is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_public_key is already registered to another device_id",
        )

    now = _utc_now()
    client_address = existing.client_address if existing is not None else _allocate_client_address()
    provisioned = existing.provisioned if existing is not None else False

    if not provisioned and _gateway_url(server):
        _provision_peer(server, registration.client_public_key, client_address)
        provisioned = True

    DEVICES[registration.device_id] = DeviceRecord(
        device_id=registration.device_id,
        client_public_key=registration.client_public_key,
        app_version=registration.app_version,
        server_id=server.id,
        client_address=client_address,
        created_at=existing.created_at if existing is not None else now,
        last_seen_at=now,
        provisioned=provisioned,
    )

    return DeviceRegistrationResponse(
        status="accepted",
        device_id=registration.device_id,
        server=server,
        client_address=client_address,
        provisioned=provisioned,
        registered_at=DEVICES[registration.device_id].created_at,
    )


@app.delete("/v1/devices/{device_id}", response_model=DeviceRevocationResponse)
def revoke_device(
    device_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> DeviceRevocationResponse:
    _require_control_plane_auth(authorization)

    record = DEVICES.get(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    server = next((item for item in SERVERS if item.id == record.server_id), None)
    if server is None:
        raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")

    if record.provisioned and _gateway_url(server):
        _revoke_peer(server, record.client_public_key)

    del DEVICES[device_id]
    return DeviceRevocationResponse(status="revoked", device_id=device_id)
