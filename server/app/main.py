from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import os
import secrets
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from .storage import DeviceStore

app = FastAPI(title="TunnelPilot Control Plane", version="0.5.0")

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
DATABASE_PATH = os.getenv("TUNNELPILOT_DATABASE_PATH", "server/data/tunnelpilot.db")


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
        return _validate_public_key(value)


class DeviceRecord(BaseModel):
    device_id: str
    client_public_key: str
    app_version: str
    server_id: str
    client_address: str
    created_at: datetime
    last_seen_at: datetime
    provisioned: bool = False
    device_token_hash: str | None = None


class DeviceRegistrationResponse(BaseModel):
    status: str
    device_id: str
    server: Server
    client_address: str
    provisioned: bool
    registered_at: datetime
    device_token: str | None = None


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

DEVICE_STORE = DeviceStore(DATABASE_PATH)
DEVICES: dict[str, DeviceRecord] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_public_key(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("client_public_key must be standard base64") from exc
    if len(decoded) != 32:
        raise ValueError("client_public_key must decode to exactly 32 bytes")
    return value


def _record_from_row(row: dict) -> DeviceRecord:
    return DeviceRecord(
        device_id=row["device_id"],
        client_public_key=row["client_public_key"],
        app_version=row["app_version"],
        server_id=row["server_id"],
        client_address=row["client_address"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        provisioned=bool(row["provisioned"]),
        device_token_hash=row.get("device_token_hash"),
    )


def _cache_record(record: DeviceRecord | None) -> None:
    if record is None:
        return
    DEVICES[record.device_id] = record


def _load_record(device_id: str) -> DeviceRecord | None:
    row = DEVICE_STORE.get(device_id)
    if row is None:
        return None
    record = _record_from_row(row)
    _cache_record(record)
    return record


def _require_control_plane_auth(authorization: str | None) -> None:
    if CONTROL_PLANE_TOKEN is not None and authorization != f"Bearer {CONTROL_PLANE_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_device_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _token_hash(token)


def _require_device_auth(record: DeviceRecord, device_token: str | None) -> None:
    if not record.device_token_hash or not device_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device authentication required")
    if not hmac.compare_digest(record.device_token_hash, _token_hash(device_token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")


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


def _select_server() -> Server:
    enabled = [server for server in SERVERS if server.enabled]
    if not enabled:
        raise HTTPException(status_code=503, detail="No VPN server is currently available")

    healthy: list[Server] = []
    for server in enabled:
        checked = _server_with_health(server)
        if checked.health_status == "ok" and (checked.capacity_remaining or 0) > 0:
            healthy.append(checked)

    if healthy:
        return min(
            healthy,
            key=lambda server: (-(server.capacity_remaining or 0), server.id),
        )

    if all(_gateway_url(server) is None for server in enabled):
        return enabled[0]

    raise HTTPException(status_code=503, detail="No healthy VPN server with available capacity is currently available")


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
    x_device_token: Annotated[str | None, Header()] = None,
) -> DeviceRegistrationResponse:
    _require_control_plane_auth(authorization)

    existing = _load_record(registration.device_id)
    issued_token: str | None = None

    if existing is not None:
        _require_device_auth(existing, x_device_token)
        if existing.client_public_key != registration.client_public_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device_id is already registered with a different public key",
            )
        server = next((item for item in SERVERS if item.id == existing.server_id and item.enabled), None)
        if server is None:
            raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")
        client_address = existing.client_address
        created_at = existing.created_at
    else:
        same_key = DEVICE_STORE.find_by_public_key(registration.client_public_key)
        if same_key is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="client_public_key is already registered to another device_id",
            )
        server = _select_server()
        issued_token, token_hash = _issue_device_token()
        now = _utc_now()
        try:
            row = DEVICE_STORE.create(
                device_id=registration.device_id,
                client_public_key=registration.client_public_key,
                app_version=registration.app_version,
                server_id=server.id,
                created_at=now.isoformat(),
                last_seen_at=now.isoformat(),
                vpn_address_pool=VPN_ADDRESS_POOL,
                vpn_gateway_address=VPN_GATEWAY_ADDRESS,
                device_token_hash=token_hash,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        existing = _record_from_row(row)
        client_address = existing.client_address
        created_at = existing.created_at

    # wg set is idempotent and repairs the peer if the gateway lost it.
    if _gateway_url(server):
        _provision_peer(server, registration.client_public_key, client_address)
        provisioned = True
    else:
        provisioned = existing.provisioned

    now = _utc_now()
    DEVICE_STORE.update(
        device_id=registration.device_id,
        app_version=registration.app_version,
        last_seen_at=now.isoformat(),
        provisioned=provisioned,
    )
    record = _load_record(registration.device_id)
    if record is None:
        raise HTTPException(status_code=500, detail="Device state could not be persisted")

    return DeviceRegistrationResponse(
        status="accepted",
        device_id=record.device_id,
        server=server,
        client_address=record.client_address,
        provisioned=record.provisioned,
        registered_at=created_at,
        device_token=issued_token,
    )


@app.delete("/v1/devices/{device_id}", response_model=DeviceRevocationResponse)
def revoke_device(
    device_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> DeviceRevocationResponse:
    _require_control_plane_auth(authorization)

    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    server = next((item for item in SERVERS if item.id == record.server_id), None)
    if server is None:
        raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")

    if record.provisioned and _gateway_url(server):
        _revoke_peer(server, record.client_public_key)

    DEVICE_STORE.delete(device_id)
    DEVICES.pop(device_id, None)
    return DeviceRevocationResponse(status="revoked", device_id=device_id)
