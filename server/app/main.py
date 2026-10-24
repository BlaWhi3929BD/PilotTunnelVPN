from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import os
import secrets
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlparse

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .storage import DeviceStore

RECONCILE_ON_STARTUP = os.getenv("TUNNELPILOT_RECONCILE_ON_STARTUP", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENVIRONMENT = (
    os.getenv("TUNNELPILOT_ENV")
    or os.getenv("TUNNELPILOT_ENVIRONMENT")
    or "development"
).strip().lower()
ALLOW_OPEN_REGISTRATION = os.getenv("TUNNELPILOT_ALLOW_OPEN_REGISTRATION", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALLOW_NONSTANDARD_WG_INTERFACE = os.getenv(
    "TUNNELPILOT_ALLOW_NONSTANDARD_WG_INTERFACE", "false"
).lower() in {"1", "true", "yes", "on"}
REQUIRE_HTTPS = os.getenv("TUNNELPILOT_REQUIRE_HTTPS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALLOW_INSECURE_GATEWAY_HTTP = os.getenv(
    "TUNNELPILOT_ALLOW_INSECURE_GATEWAY_HTTP", "false"
).lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    _validate_runtime_configuration()
    if RECONCILE_ON_STARTUP:
        for server in _catalog_servers(include_disabled=False):
            if server.enabled and _gateway_url(server):
                try:
                    # Startup reconciliation is strictly non-destructive (prune_unknown=False).
                    _reconcile_server(server, dry_run=False, prune_unknown=False)
                except Exception:
                    pass
    yield


app = FastAPI(title="TunnelPilot Control Plane", version="0.7.0", lifespan=_lifespan)

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
_DEFAULT_DATABASE_PATH = str(
    Path(__file__).resolve().parents[2] / "server" / "data" / "tunnelpilot.db"
)
DATABASE_PATH = os.getenv("TUNNELPILOT_DATABASE_PATH", _DEFAULT_DATABASE_PATH)
GATEWAY_HEALTH_CACHE_TTL = float(os.getenv("TUNNELPILOT_GATEWAY_HEALTH_CACHE_TTL", "3.0"))
_GATEWAY_HEALTH_CACHE: dict[str, tuple[float, dict[str, int | str | bool]]] = {}

REGISTRATION_RATE_LIMIT_WINDOW = float(os.getenv("TUNNELPILOT_REGISTRATION_RATE_LIMIT_WINDOW", "60.0"))
REGISTRATION_RATE_LIMIT_MAX = int(os.getenv("TUNNELPILOT_REGISTRATION_RATE_LIMIT_MAX", "15"))
_REGISTRATION_REQUEST_HISTORY: dict[str, list[float]] = {}


class Server(BaseModel):
    id: str
    region: str
    hostname: str
    public_key: str
    port: int = Field(default=51820, ge=1, le=65535)
    enabled: bool = True
    tier: str = "free"
    gateway_api_url: str | None = Field(default=None, exclude=True)
    gateway_agent_token: str | None = Field(default=None, exclude=True)
    vpn_address_pool: str = Field(default="10.67.0.0/24", exclude=True)
    vpn_gateway_address: str = Field(default="10.67.0.1", exclude=True)
    configured_peer_capacity: int = Field(default=240, exclude=True)
    health_status: str = "unknown"
    peer_count: int | None = None
    peer_capacity: int | None = None
    capacity_remaining: int | None = None


class ServerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    region: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    public_key: str
    port: int = Field(default=51820, ge=1, le=65535)
    enabled: bool = True
    gateway_api_url: str | None = None
    gateway_agent_token: str | None = None
    vpn_address_pool: str = "10.67.0.0/24"
    vpn_gateway_address: str = "10.67.0.1"
    peer_capacity: int = Field(default=240, ge=1, le=65534)
    tier: str = Field(default="free", pattern=r"^(free|premium)$")

    @field_validator("public_key")
    @classmethod
    def validate_server_public_key(cls, value: str) -> str:
        return _validate_public_key(value)

    @field_validator("gateway_api_url")
    @classmethod
    def validate_server_gateway_url(cls, value: str | None) -> str | None:
        return _validate_gateway_api_url(value)


class ServerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: str | None = Field(default=None, min_length=1, max_length=64)
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    public_key: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool | None = None
    gateway_api_url: str | None = None
    gateway_agent_token: str | None = None
    vpn_address_pool: str | None = None
    vpn_gateway_address: str | None = None
    peer_capacity: int | None = Field(default=None, ge=1, le=65534)
    tier: str | None = Field(default=None, pattern=r"^(free|premium)$")

    @field_validator("public_key")
    @classmethod
    def validate_optional_public_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_public_key(value)

    @field_validator("gateway_api_url")
    @classmethod
    def validate_optional_gateway_url(cls, value: str | None) -> str | None:
        return _validate_gateway_api_url(value)


class ServerDeleteResponse(BaseModel):
    status: str
    server_id: str


class DeviceRegistration(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    client_public_key: str
    app_version: str = Field(min_length=1, max_length=32)
    server_id: str | None = Field(default=None, min_length=2, max_length=64)
    region: str | None = Field(default=None, min_length=1, max_length=64)

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
    tier: str = "free"


class DeviceRegistrationResponse(BaseModel):
    status: str
    device_id: str
    server: Server
    client_address: str
    provisioned: bool
    registered_at: datetime
    device_token: str | None = None
    tier: str = "free"


class DeviceRevocationResponse(BaseModel):
    status: str
    device_id: str


class DeviceRotationRequest(BaseModel):
    client_public_key: str
    app_version: str = Field(min_length=1, max_length=32)

    @field_validator("client_public_key")
    @classmethod
    def validate_client_public_key(cls, value: str) -> str:
        return _validate_public_key(value)


class DeviceRotationResponse(BaseModel):
    status: str
    device_id: str
    client_address: str
    provisioned: bool
    server: Server
    tier: str = "free"


class DeviceMigrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_server_id: str = Field(min_length=2, max_length=64)
    app_version: str | None = Field(default=None, min_length=1, max_length=32)


class DeviceMigrationResponse(BaseModel):
    status: str
    device_id: str
    previous_server_id: str
    client_address: str
    provisioned: bool
    server: Server
    tier: str = "free"


class DeviceTierUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str = Field(pattern=r"^(free|premium)$")
    purchase_token: str | None = None


class DeviceTierUpdateResponse(BaseModel):
    status: str
    device_id: str
    tier: str


class ReconcileOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool | None = None
    prune_unknown: bool | None = None
    confirm_empty_db: bool | None = None


class ServerReconcileReport(BaseModel):
    server_id: str
    status: str
    dry_run: bool = False
    prune_unknown: bool = False
    restored_peers: int = 0
    removed_peers: int = 0
    would_restore_peers: int = 0
    would_remove_peers: int = 0
    unknown_peers: int = 0
    unmanaged_peers: int = 0
    detail: str | None = None


SERVERS = [
    Server(
        id=SERVER_ID,
        region=SERVER_REGION,
        hostname=SERVER_HOSTNAME,
        public_key=SERVER_PUBLIC_KEY,
        port=SERVER_PORT,
        enabled=SERVER_ENABLED,
        gateway_api_url=GATEWAY_AGENT_URL,
        vpn_address_pool=VPN_ADDRESS_POOL,
        vpn_gateway_address=VPN_GATEWAY_ADDRESS,
    )
]

DEVICE_STORE = DeviceStore(DATABASE_PATH)
DEVICES: dict[str, DeviceRecord] = {}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_FORBIDDEN_METADATA_HOSTS = {
    "169.254.169.254",
    "fd00:ec2::254",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_public_key(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("public_key must be standard base64") from exc
    if len(decoded) != 32:
        raise ValueError("public_key must decode to exactly 32 bytes")
    return value


def _validate_gateway_api_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("gateway_api_url must be a valid http:// or https:// URL")
    if parsed.username or parsed.password:
        raise ValueError("gateway_api_url must not contain embedded user credentials")
    if host in _FORBIDDEN_METADATA_HOSTS or host.endswith(".internal"):
        raise ValueError("gateway_api_url cannot target cloud metadata or internal metadata hosts")
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None
    if ip_obj is not None:
        if (
            ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
            or str(ip_obj) in _FORBIDDEN_METADATA_HOSTS
        ):
            raise ValueError("gateway_api_url cannot target link-local, multicast, unspecified, or metadata IPs")
    if ENVIRONMENT == "production" and scheme == "http" and host not in _LOOPBACK_HOSTS and not ALLOW_INSECURE_GATEWAY_HTTP:
        raise ValueError("gateway_api_url must use https:// or loopback in production")
    return cleaned


def _server_from_row(row: dict) -> Server:
    return Server(
        id=str(row["server_id"]),
        region=str(row["region"]),
        hostname=str(row["hostname"]),
        public_key=str(row["public_key"]),
        port=int(row["port"]),
        enabled=bool(row["enabled"]),
        tier=str(row.get("tier") or "free"),
        gateway_api_url=row.get("gateway_api_url"),
        gateway_agent_token=row.get("gateway_agent_token"),
        vpn_address_pool=str(row.get("vpn_address_pool") or VPN_ADDRESS_POOL),
        vpn_gateway_address=str(row.get("vpn_gateway_address") or VPN_GATEWAY_ADDRESS),
        configured_peer_capacity=int(row.get("peer_capacity") or 240),
    )


def _sync_default_server_catalog() -> None:
    if not SERVERS:
        return
    default_srv = SERVERS[0]
    DEVICE_STORE.ensure_default_server(
        server_id=default_srv.id,
        region=default_srv.region,
        hostname=default_srv.hostname,
        port=default_srv.port,
        public_key=default_srv.public_key,
        enabled=default_srv.enabled,
        gateway_api_url=default_srv.gateway_api_url or GATEWAY_AGENT_URL,
        gateway_agent_token=default_srv.gateway_agent_token,
        vpn_address_pool=VPN_ADDRESS_POOL,
        vpn_gateway_address=VPN_GATEWAY_ADDRESS,
        peer_capacity=default_srv.configured_peer_capacity,
        tier=default_srv.tier,
    )


def _catalog_servers(*, include_disabled: bool = True) -> list[Server]:
    _sync_default_server_catalog()
    rows = DEVICE_STORE.list_servers(include_disabled=include_disabled)
    return [_server_from_row(row) for row in rows]


def _get_catalog_server(server_id: str, *, require_enabled: bool = False) -> Server | None:
    _sync_default_server_catalog()
    row = DEVICE_STORE.get_server(server_id)
    if row is None:
        return None
    srv = _server_from_row(row)
    if require_enabled and not srv.enabled:
        return None
    return srv


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
        tier=str(row.get("tier") or "free"),
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


def _has_configured_admin_token() -> bool:
    return bool(CONTROL_PLANE_TOKEN and CONTROL_PLANE_TOKEN.strip())


def _is_valid_admin_token(authorization: str | None) -> bool:
    if not _has_configured_admin_token() or not authorization:
        return False
    expected = f"Bearer {CONTROL_PLANE_TOKEN}"
    return hmac.compare_digest(authorization, expected)


def _require_admin_auth(authorization: str | None) -> None:
    """Strictly enforces administrative Bearer token authentication.

    Never affected by TUNNELPILOT_ALLOW_OPEN_REGISTRATION. Fails closed with 503
    if TUNNELPILOT_CONTROL_PLANE_TOKEN is not configured, and 401 if missing/invalid.
    """
    if not _has_configured_admin_token():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control plane admin token is not configured",
        )
    if not _is_valid_admin_token(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _require_registration_auth(authorization: str | None) -> None:
    """Enforces client device enrollment policy on POST /v1/devices only.

    Never used for administrative endpoints (reconcile, admin revocation, force delete).
    """
    if ALLOW_OPEN_REGISTRATION:
        if authorization is not None and not _is_valid_admin_token(authorization):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        return
    if _has_configured_admin_token():
        if not _is_valid_admin_token(authorization):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        return
    if ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control plane enrollment token is required in production unless TUNNELPILOT_ALLOW_OPEN_REGISTRATION=true",
        )


def _enforce_production_transport_security(request: Request) -> None:
    if ENVIRONMENT != "production" or not REQUIRE_HTTPS:
        return
    forwarded_proto = request.headers.get("x-forwarded-proto", "").strip().lower()
    if forwarded_proto:
        first_proto = forwarded_proto.split(",")[0].strip()
        if first_proto != "https":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HTTPS is required for control plane requests in production",
            )
        return
    scheme = (request.url.scheme or "").lower()
    hostname = (request.url.hostname or "").lower()
    if scheme != "https" and hostname not in (_LOOPBACK_HOSTS | {"testserver"}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HTTPS is required for control plane requests in production",
        )


def _validate_runtime_configuration() -> None:
    if ENVIRONMENT != "production":
        return
    if not CONTROL_PLANE_TOKEN or not CONTROL_PLANE_TOKEN.strip():
        raise RuntimeError("TUNNELPILOT_CONTROL_PLANE_TOKEN must be configured in production")
    enabled_servers = _catalog_servers(include_disabled=False)
    if not enabled_servers:
        raise RuntimeError("At least one enabled VPN server is required in production")
    for srv in enabled_servers:
        gw_url = _gateway_url(srv)
        gw_token = _gateway_token(srv)
        if not gw_url or not gw_token or not gw_token.strip():
            raise RuntimeError(
                f"Gateway agent URL and token must be configured for server '{srv.id}' in production"
            )
        if CONTROL_PLANE_TOKEN.strip() == gw_token.strip():
            raise RuntimeError(
                "TUNNELPILOT_CONTROL_PLANE_TOKEN and TUNNELPILOT_GATEWAY_AGENT_TOKEN must be distinct in production"
            )
        try:
            _validate_gateway_api_url(gw_url)
        except ValueError as exc:
            raise RuntimeError(
                f"Gateway agent URL for server '{srv.id}' is invalid in production: {exc}"
            ) from exc
        if not srv.hostname.strip() or srv.hostname.strip() == "replace-with-real-gateway":
            raise RuntimeError(
                f"Server '{srv.id}' has a placeholder or empty hostname in production"
            )
        try:
            _validate_public_key(srv.public_key)
        except ValueError as exc:
            raise RuntimeError(
                f"Server '{srv.id}' has an invalid WireGuard public key in production"
            ) from exc


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


def _gateway_token(server: Server) -> str | None:
    return server.gateway_agent_token or GATEWAY_AGENT_TOKEN


def _gateway_headers(server: Server) -> dict[str, str]:
    token = _gateway_token(server)
    if not token:
        raise HTTPException(status_code=503, detail="Gateway agent token is not configured")
    return {"Authorization": f"Bearer {token}"}


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
            return client.request(method, path, headers=_gateway_headers(server), json=json)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Gateway agent is unreachable") from exc


def _probe_gateway(server: Server, *, force_refresh: bool = False) -> dict[str, int | str | bool]:
    if not force_refresh:
        cached = _GATEWAY_HEALTH_CACHE.get(server.id)
        if cached is not None:
            cached_at, cached_result = cached
            if time.monotonic() - cached_at < GATEWAY_HEALTH_CACHE_TTL:
                return cached_result

    base_url = _gateway_url(server)
    allocated_in_db = DEVICE_STORE.count_devices_for_server(server.id)
    configured_cap = server.configured_peer_capacity
    if not base_url:
        remaining_db = max(0, configured_cap - allocated_in_db)
        res: dict[str, int | str | bool] = {
            "status": "unconfigured",
            "wireguard_available": False,
            "peer_count": allocated_in_db,
            "peer_capacity": configured_cap,
            "capacity_remaining": remaining_db,
        }
        _GATEWAY_HEALTH_CACHE[server.id] = (time.monotonic(), res)
        return res

    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=GATEWAY_HEALTH_TIMEOUT) as client:
            response = client.get("/healthz")
    except httpx.HTTPError:
        res = {
            "status": "unreachable",
            "wireguard_available": False,
            "peer_count": allocated_in_db,
            "peer_capacity": configured_cap,
            "capacity_remaining": 0,
        }
        _GATEWAY_HEALTH_CACHE[server.id] = (time.monotonic(), res)
        return res

    if response.status_code >= 300:
        res = {
            "status": "degraded",
            "wireguard_available": False,
            "peer_count": allocated_in_db,
            "peer_capacity": configured_cap,
            "capacity_remaining": 0,
        }
        _GATEWAY_HEALTH_CACHE[server.id] = (time.monotonic(), res)
        return res

    try:
        payload = response.json()
    except ValueError:
        res = {
            "status": "degraded",
            "wireguard_available": False,
            "peer_count": allocated_in_db,
            "peer_capacity": configured_cap,
            "capacity_remaining": 0,
        }
        _GATEWAY_HEALTH_CACHE[server.id] = (time.monotonic(), res)
        return res

    gw_peer_count = int(payload.get("peer_count", 0))
    gw_peer_capacity = int(payload.get("peer_capacity", configured_cap))
    effective_capacity = min(configured_cap, gw_peer_capacity) if gw_peer_capacity > 0 else configured_cap
    effective_count = max(allocated_in_db, gw_peer_count)
    remaining = max(0, min(int(payload.get("capacity_remaining", effective_capacity - effective_count)), effective_capacity - effective_count))
    wireguard_available = bool(payload.get("wireguard_available", False))
    health_status = str(payload.get("status", "degraded"))
    if not wireguard_available:
        health_status = "degraded"
    elif remaining == 0 and health_status == "ok":
        health_status = "full"

    res = {
        "status": health_status,
        "wireguard_available": wireguard_available,
        "peer_count": effective_count,
        "peer_capacity": effective_capacity,
        "capacity_remaining": remaining,
    }
    _GATEWAY_HEALTH_CACHE[server.id] = (time.monotonic(), res)
    return res


def _server_with_health(server: Server, *, force_refresh: bool = False) -> Server:
    health = _probe_gateway(server, force_refresh=force_refresh)
    return server.model_copy(
        update={
            "health_status": health["status"],
            "peer_count": health["peer_count"],
            "peer_capacity": health["peer_capacity"],
            "capacity_remaining": health["capacity_remaining"],
        }
    )


def _select_server(
    *,
    preferred_server_id: str | None = None,
    preferred_region: str | None = None,
    device_tier: str = "free",
) -> Server:
    all_servers = _catalog_servers(include_disabled=True)
    if preferred_server_id is not None:
        target = next((s for s in all_servers if s.id == preferred_server_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Requested VPN server '{preferred_server_id}' not found")
        if not target.enabled:
            raise HTTPException(status_code=503, detail=f"Requested VPN server '{preferred_server_id}' is disabled")
        if target.tier == "premium" and device_tier != "premium":
            raise HTTPException(status_code=403, detail="Premium tier is required for the selected VPN server")
        checked = _server_with_health(target)
        if _gateway_url(checked) is not None and (checked.health_status != "ok" or (checked.capacity_remaining or 0) <= 0):
            raise HTTPException(
                status_code=503,
                detail=f"Requested VPN server '{preferred_server_id}' is currently {checked.health_status}",
            )
        if (checked.capacity_remaining or 0) <= 0:
            raise HTTPException(
                status_code=503,
                detail=f"Requested VPN server '{preferred_server_id}' has reached its peer capacity",
            )
        return checked

    enabled = [server for server in all_servers if server.enabled]
    if preferred_region is not None:
        enabled = [s for s in enabled if s.region.lower() == preferred_region.strip().lower()]
        if not enabled:
            raise HTTPException(
                status_code=503,
                detail=f"No enabled VPN server is available in region '{preferred_region}'",
            )

    eligible = [
        s for s in enabled if s.tier == "free" or device_tier == "premium"
    ]
    if not eligible:
        if any(s.tier == "premium" for s in enabled):
            raise HTTPException(status_code=403, detail="Premium tier is required for available VPN servers")
        raise HTTPException(status_code=503, detail="No VPN server is currently available")

    healthy: list[Server] = []
    unconfigured_with_cap: list[Server] = []
    for server in eligible:
        checked = _server_with_health(server)
        if checked.health_status == "ok" and (checked.capacity_remaining or 0) > 0:
            healthy.append(checked)
        elif _gateway_url(server) is None and (checked.capacity_remaining or 0) > 0:
            unconfigured_with_cap.append(checked)

    if healthy:
        return min(
            healthy,
            key=lambda server: (-(server.capacity_remaining or 0), server.id),
        )

    if unconfigured_with_cap and all(_gateway_url(server) is None for server in eligible):
        return unconfigured_with_cap[0]

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


def _rotate_peer(server: Server, old_public_key: str, new_public_key: str, client_address: str) -> None:
    if old_public_key == new_public_key:
        return
    # Install the new peer FIRST so the old peer is never destroyed if the gateway is unreachable or rejects the new key.
    _provision_peer(server, new_public_key, client_address)
    try:
        _revoke_peer(server, old_public_key)
    except Exception:
        rollback_error = None
        try:
            # Re-bind client_address to old_public_key and clean up new_public_key
            _provision_peer(server, old_public_key, client_address)
            _revoke_peer(server, new_public_key)
        except Exception as exc:
            rollback_error = exc
        if rollback_error is not None:
            raise HTTPException(
                status_code=502,
                detail="Gateway peer rotation failed while removing old peer and rollback also failed",
            ) from rollback_error
        raise


def _list_gateway_peer_state(server: Server) -> tuple[str, list[str], dict[str, list[str]]]:
    response = _gateway_request("GET", "/v1/peers", server=server)
    if response.status_code >= 300:
        detail = response.text[:300] or "Gateway agent rejected peer listing"
        raise HTTPException(status_code=502, detail=detail)
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Gateway agent returned invalid JSON for /v1/peers") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Gateway agent returned invalid /v1/peers payload")

    interface = payload.get("interface")
    if not isinstance(interface, str) or not interface.strip():
        raise HTTPException(status_code=502, detail="Gateway agent did not report WireGuard interface name")
    if not ALLOW_NONSTANDARD_WG_INTERFACE and not interface.strip().startswith("tunnelpilot"):
        raise HTTPException(
            status_code=502,
            detail=f"Refusing to reconcile non-TunnelPilot WireGuard interface '{interface}'",
        )

    peers = payload.get("peers")
    if not isinstance(peers, list) or not all(isinstance(item, str) for item in peers):
        raise HTTPException(status_code=502, detail="Gateway agent returned invalid peers list")
    validated_peers: list[str] = []
    for peer_key in peers:
        try:
            validated_peers.append(_validate_public_key(peer_key))
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Gateway agent returned malformed peer public key",
            ) from exc

    raw_allowed = payload.get("peer_allowed_ips", {})
    if raw_allowed is None:
        raw_allowed = {}
    if not isinstance(raw_allowed, dict):
        raise HTTPException(status_code=502, detail="Gateway agent returned invalid peer_allowed_ips map")

    peer_allowed_ips: dict[str, list[str]] = {}
    for key, cidrs in raw_allowed.items():
        if not isinstance(key, str) or not isinstance(cidrs, list) or not all(isinstance(c, str) for c in cidrs):
            raise HTTPException(status_code=502, detail="Gateway agent returned malformed peer_allowed_ips entry")
        peer_allowed_ips[key] = [c.strip() for c in cidrs if c.strip()]

    return interface.strip(), validated_peers, peer_allowed_ips


def _list_gateway_peers(server: Server) -> list[str]:
    _, peers, _ = _list_gateway_peer_state(server)
    return peers


def _is_managed_pool_peer(allowed_cidrs: list[str] | None, pool_network: ipaddress.IPv4Network) -> bool:
    if allowed_cidrs is None:
        # Gateway did not report per-peer allowed-ips; interface ownership was already verified as tunnelpilot*.
        return True
    if len(allowed_cidrs) == 0:
        return True
    if len(allowed_cidrs) != 1:
        return False
    try:
        net = ipaddress.ip_network(allowed_cidrs[0], strict=True)
    except ValueError:
        return False
    return isinstance(net, ipaddress.IPv4Network) and net.prefixlen == 32 and net.network_address in pool_network


def _reconcile_server(
    server: Server,
    *,
    dry_run: bool = False,
    prune_unknown: bool = False,
    confirm_empty_db: bool = False,
) -> ServerReconcileReport:
    if not _gateway_url(server):
        return ServerReconcileReport(
            server_id=server.id,
            status="skipped",
            dry_run=dry_run,
            prune_unknown=prune_unknown,
            detail="Gateway agent URL is not configured",
        )

    effective_pool = server.vpn_address_pool or VPN_ADDRESS_POOL
    effective_gw = server.vpn_gateway_address or VPN_GATEWAY_ADDRESS
    try:
        validated_rows = DEVICE_STORE.verify_integrity(
            vpn_address_pool=effective_pool,
            vpn_gateway_address=effective_gw,
            server_id=server.id,
        )
        pool_network = ipaddress.ip_network(effective_pool, strict=True)
        if not isinstance(pool_network, ipaddress.IPv4Network):
            raise RuntimeError("TUNNELPILOT_VPN_ADDRESS_POOL must be an IPv4 network")
    except (RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Refusing gateway reconciliation due to database or pool state error: {exc}",
        ) from exc

    _, peers_list, peer_allowed_ips = _list_gateway_peer_state(server)
    active_peers = set(peers_list)

    expected_rows = [
        row
        for row in validated_rows
        if row["server_id"] == server.id and bool(row["provisioned"])
    ]
    expected_map = {
        str(row["client_public_key"]): str(row["client_address"])
        for row in expected_rows
    }

    to_restore: list[tuple[str, str]] = []
    for public_key, client_address in expected_map.items():
        if public_key not in active_peers:
            to_restore.append((public_key, client_address))
        elif public_key in peer_allowed_ips and peer_allowed_ips[public_key] != [client_address]:
            to_restore.append((public_key, client_address))

    tombstone_keys = {
        str(row["client_public_key"])
        for row in DEVICE_STORE.list_tombstones(server.id)
        if str(row["client_public_key"]) not in expected_map
    }
    tombstones_to_remove = sorted(active_peers & tombstone_keys)

    prunable_unknown: list[str] = []
    unmanaged_unknown: list[str] = []
    for unknown_key in sorted(active_peers - expected_map.keys() - tombstone_keys):
        allowed_for_peer = peer_allowed_ips.get(unknown_key) if peer_allowed_ips else None
        if _is_managed_pool_peer(allowed_for_peer, pool_network):
            prunable_unknown.append(unknown_key)
        else:
            unmanaged_unknown.append(unknown_key)

    if prune_unknown and len(expected_map) == 0 and len(prunable_unknown) > 0 and not confirm_empty_db:
        raise HTTPException(
            status_code=409,
            detail=(
                "Refusing to prune active gateway peers against an empty server device inventory; "
                "pass confirm_empty_db=true to explicitly allow pruning all peers"
            ),
        )

    if dry_run:
        would_remove = len(tombstones_to_remove) + (len(prunable_unknown) if prune_unknown else 0)
        return ServerReconcileReport(
            server_id=server.id,
            status="dry_run",
            dry_run=True,
            prune_unknown=prune_unknown,
            restored_peers=0,
            removed_peers=0,
            would_restore_peers=len(to_restore),
            would_remove_peers=would_remove,
            unknown_peers=len(prunable_unknown),
            unmanaged_peers=len(unmanaged_unknown),
        )

    restored = 0
    for public_key, client_address in to_restore:
        _provision_peer(server, public_key, client_address)
        DEVICE_STORE.remove_tombstone(server.id, public_key)
        restored += 1

    removed = 0
    for tomb_key in tombstones_to_remove:
        _revoke_peer(server, tomb_key)
        DEVICE_STORE.remove_tombstone(server.id, tomb_key)
        removed += 1
    for cleared_tomb in tombstone_keys - active_peers:
        DEVICE_STORE.remove_tombstone(server.id, cleared_tomb)

    if prune_unknown:
        for stale_key in prunable_unknown:
            _revoke_peer(server, stale_key)
            removed += 1

    return ServerReconcileReport(
        server_id=server.id,
        status="reconciled",
        dry_run=False,
        prune_unknown=prune_unknown,
        restored_peers=restored,
        removed_peers=removed,
        would_restore_peers=restored,
        would_remove_peers=removed,
        unknown_peers=len(prunable_unknown),
        unmanaged_peers=len(unmanaged_unknown),
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/servers", response_model=list[Server])
def list_servers(
    request: Request,
    include_disabled: bool = False,
    region: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> list[Server]:
    if include_disabled:
        _enforce_production_transport_security(request)
        _require_admin_auth(authorization)
    servers = _catalog_servers(include_disabled=include_disabled)
    if region is not None:
        servers = [s for s in servers if s.region.lower() == region.strip().lower()]
    healthy = [_server_with_health(server) for server in servers]
    return sorted(
        healthy,
        key=lambda server: (
            not server.enabled,
            server.health_status not in {"ok", "full"},
            -(server.capacity_remaining or 0),
            server.id,
        ),
    )


@app.post("/v1/servers", response_model=Server, status_code=status.HTTP_201_CREATED)
def create_server_endpoint(
    request: Request,
    payload: ServerCreateRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> Server:
    _enforce_production_transport_security(request)
    _require_admin_auth(authorization)
    _sync_default_server_catalog()
    try:
        row = DEVICE_STORE.create_server(
            server_id=payload.id,
            region=payload.region,
            hostname=payload.hostname,
            port=payload.port,
            public_key=payload.public_key,
            enabled=payload.enabled,
            gateway_api_url=payload.gateway_api_url,
            gateway_agent_token=payload.gateway_agent_token,
            vpn_address_pool=payload.vpn_address_pool,
            vpn_gateway_address=payload.vpn_gateway_address,
            peer_capacity=payload.peer_capacity,
            tier=payload.tier,
        )
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg) from exc
    srv = _server_from_row(row)
    return _server_with_health(srv)


@app.patch("/v1/servers/{server_id}", response_model=Server)
@app.put("/v1/servers/{server_id}", response_model=Server)
def update_server_endpoint(
    server_id: str,
    request: Request,
    payload: ServerUpdateRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> Server:
    _enforce_production_transport_security(request)
    _require_admin_auth(authorization)
    _sync_default_server_catalog()
    fields_set = payload.model_fields_set
    try:
        row = DEVICE_STORE.update_server(
            server_id,
            region=payload.region,
            hostname=payload.hostname,
            port=payload.port,
            public_key=payload.public_key,
            enabled=payload.enabled,
            gateway_api_url=payload.gateway_api_url,
            update_gateway_api_url="gateway_api_url" in fields_set,
            gateway_agent_token=payload.gateway_agent_token,
            update_gateway_agent_token="gateway_agent_token" in fields_set,
            vpn_address_pool=payload.vpn_address_pool,
            vpn_gateway_address=payload.vpn_gateway_address,
            peer_capacity=payload.peer_capacity,
            tier=payload.tier,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found") from exc
    except ValueError as exc:
        msg = str(exc)
        if "incompatible" in msg or "Cannot reduce" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg) from exc

    updated_srv = _server_from_row(row)
    _GATEWAY_HEALTH_CACHE.pop(server_id, None)
    for idx, mem_srv in enumerate(SERVERS):
        if mem_srv.id == server_id:
            SERVERS[idx] = updated_srv
    return _server_with_health(updated_srv, force_refresh=True)


@app.delete("/v1/servers/{server_id}", response_model=ServerDeleteResponse)
def delete_server_endpoint(
    server_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ServerDeleteResponse:
    _enforce_production_transport_security(request)
    _require_admin_auth(authorization)
    _sync_default_server_catalog()
    try:
        DEVICE_STORE.delete_server(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _GATEWAY_HEALTH_CACHE.pop(server_id, None)
    SERVERS[:] = [s for s in SERVERS if s.id != server_id]
    return ServerDeleteResponse(status="deleted", server_id=server_id)


_ALLOWED_RECONCILE_QUERY_PARAMS = {"dry_run", "prune_unknown", "confirm_empty_db"}


def _resolve_reconcile_options(
    request: Request,
    options: ReconcileOptions | None,
    dry_run: bool | None,
    prune_unknown: bool | None,
    confirm_empty_db: bool | None,
) -> tuple[bool, bool, bool]:
    unknown_query = sorted(set(request.query_params.keys()) - _ALLOWED_RECONCILE_QUERY_PARAMS)
    if unknown_query:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown reconciliation query parameter(s): {', '.join(unknown_query)}",
        )

    def _merge(name: str, query_val: bool | None, body_val: bool | None) -> bool:
        if query_val is not None and body_val is not None and query_val != body_val:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Conflicting values for '{name}' between query parameter and JSON body",
            )
        if query_val is not None:
            return query_val
        if body_val is not None:
            return body_val
        return False

    resolved_dry_run = _merge("dry_run", dry_run, options.dry_run if options else None)
    resolved_prune = _merge("prune_unknown", prune_unknown, options.prune_unknown if options else None)
    resolved_confirm = _merge(
        "confirm_empty_db",
        confirm_empty_db,
        options.confirm_empty_db if options else None,
    )
    return resolved_dry_run, resolved_prune, resolved_confirm


@app.post("/v1/servers/reconcile", response_model=list[ServerReconcileReport])
def reconcile_servers(
    request: Request,
    options: Annotated[ReconcileOptions | None, Body()] = None,
    authorization: Annotated[str | None, Header()] = None,
    dry_run: Annotated[bool | None, Query()] = None,
    prune_unknown: Annotated[bool | None, Query()] = None,
    confirm_empty_db: Annotated[bool | None, Query()] = None,
) -> list[ServerReconcileReport]:
    _enforce_production_transport_security(request)
    _require_admin_auth(authorization)
    resolved_dry_run, resolved_prune, resolved_confirm = _resolve_reconcile_options(
        request,
        options,
        dry_run,
        prune_unknown,
        confirm_empty_db,
    )
    try:
        enabled = _catalog_servers(include_disabled=False)
    except (RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Refusing gateway reconciliation due to database or pool state error: {exc}",
        ) from exc
    reports: list[ServerReconcileReport] = []
    for idx, server in enumerate(enabled):
        try:
            reports.append(
                _reconcile_server(
                    server,
                    dry_run=resolved_dry_run,
                    prune_unknown=resolved_prune,
                    confirm_empty_db=resolved_confirm,
                )
            )
        except HTTPException as exc:
            # If multiple servers are configured and one gateway is unreachable (502),
            # isolate the gateway failure in the batch report instead of aborting healthy servers.
            if len(enabled) > 1 and exc.status_code == 502:
                reports.append(
                    ServerReconcileReport(
                        server_id=server.id,
                        status="error",
                        dry_run=resolved_dry_run,
                        prune_unknown=resolved_prune,
                        detail=str(exc.detail),
                    )
                )
            else:
                raise
    return reports


@app.post("/v1/servers/{server_id}/reconcile", response_model=ServerReconcileReport)
def reconcile_single_server(
    server_id: str,
    request: Request,
    options: Annotated[ReconcileOptions | None, Body()] = None,
    authorization: Annotated[str | None, Header()] = None,
    dry_run: Annotated[bool | None, Query()] = None,
    prune_unknown: Annotated[bool | None, Query()] = None,
    confirm_empty_db: Annotated[bool | None, Query()] = None,
) -> ServerReconcileReport:
    _enforce_production_transport_security(request)
    _require_admin_auth(authorization)
    resolved_dry_run, resolved_prune, resolved_confirm = _resolve_reconcile_options(
        request,
        options,
        dry_run,
        prune_unknown,
        confirm_empty_db,
    )
    try:
        server = _get_catalog_server(server_id, require_enabled=True)
    except (RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Refusing gateway reconciliation due to database or pool state error: {exc}",
        ) from exc
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return _reconcile_server(
        server,
        dry_run=resolved_dry_run,
        prune_unknown=resolved_prune,
        confirm_empty_db=resolved_confirm,
    )


def _check_registration_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    now = time.monotonic()
    cutoff = now - REGISTRATION_RATE_LIMIT_WINDOW
    history = [ts for ts in _REGISTRATION_REQUEST_HISTORY.get(client_ip, []) if ts > cutoff]
    if len(history) >= REGISTRATION_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many device registration attempts from this IP address; please wait before registering again",
        )
    history.append(now)
    _REGISTRATION_REQUEST_HISTORY[client_ip] = history


@app.post("/v1/devices", response_model=DeviceRegistrationResponse)
def register_device(
    request: Request,
    registration: DeviceRegistration,
    authorization: Annotated[str | None, Header()] = None,
    x_device_token: Annotated[str | None, Header()] = None,
) -> DeviceRegistrationResponse:
    _enforce_production_transport_security(request)
    _require_registration_auth(authorization)

    existing = _load_record(registration.device_id)
    issued_token: str | None = None

    if existing is not None:
        _require_device_auth(existing, x_device_token)
        if existing.client_public_key != registration.client_public_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device_id is already registered with a different public key",
            )
        if registration.server_id is not None and registration.server_id != existing.server_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Device is pinned to server '{existing.server_id}'; "
                    "use POST /v1/devices/{device_id}/migrate to switch servers"
                ),
            )
        server = _get_catalog_server(existing.server_id, require_enabled=True)
        if server is None:
            raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")
        client_address = existing.client_address
        created_at = existing.created_at
    else:
        _check_registration_rate_limit(request)
        same_key = DEVICE_STORE.find_by_public_key(registration.client_public_key)
        if same_key is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="client_public_key is already registered to another device_id",
            )
        server = _select_server(
            preferred_server_id=registration.server_id,
            preferred_region=registration.region,
            device_tier="free",
        )
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
                vpn_address_pool=server.vpn_address_pool,
                vpn_gateway_address=server.vpn_gateway_address,
                device_token_hash=token_hash,
                peer_capacity=server.configured_peer_capacity,
                tier="free",
            )
        except ValueError as exc:
            if "Address pool exhausted" in str(exc):
                raise HTTPException(status_code=503, detail="Server address pool is fully allocated") from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        existing = _record_from_row(row)
        client_address = existing.client_address
        created_at = existing.created_at

    try:
        # wg set is idempotent and repairs the peer if the gateway lost it.
        if _gateway_url(server):
            _provision_peer(server, registration.client_public_key, client_address)
            DEVICE_STORE.remove_tombstone(server.id, registration.client_public_key)
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
    except Exception:
        if issued_token is not None:
            # If initial provisioning failed, the client never receives the issued token.
            # Roll back newly created storage record and cache so the device is not stranded in a 401 lockout.
            DEVICE_STORE.delete(registration.device_id)
            DEVICES.pop(registration.device_id, None)
            if _gateway_url(server):
                try:
                    _revoke_peer(server, registration.client_public_key)
                except Exception:
                    pass
        raise

    return DeviceRegistrationResponse(
        status="accepted",
        device_id=record.device_id,
        server=server,
        client_address=record.client_address,
        provisioned=record.provisioned,
        registered_at=created_at,
        device_token=issued_token,
        tier=record.tier,
    )


@app.post("/v1/devices/{device_id}/rotate", response_model=DeviceRotationResponse)
def rotate_device_key(
    request: Request,
    device_id: str,
    rotation: DeviceRotationRequest,
    x_device_token: Annotated[str | None, Header()] = None,
) -> DeviceRotationResponse:
    _enforce_production_transport_security(request)
    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    _require_device_auth(record, x_device_token)

    if rotation.client_public_key == record.client_public_key:
        server = _get_catalog_server(record.server_id, require_enabled=True)
        if server is None:
            raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")
        if _gateway_url(server):
            _provision_peer(server, record.client_public_key, record.client_address)
            if not record.provisioned:
                DEVICE_STORE.update(
                    device_id=device_id,
                    last_seen_at=_utc_now().isoformat(),
                    provisioned=True,
                )
                record = _load_record(device_id) or record
        return DeviceRotationResponse(
            status="unchanged",
            device_id=record.device_id,
            client_address=record.client_address,
            provisioned=record.provisioned,
            server=server,
        )

    conflicting = DEVICE_STORE.find_by_public_key(rotation.client_public_key)
    if conflicting is not None and conflicting["device_id"] != device_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_public_key is already registered to another device_id",
        )

    server = _get_catalog_server(record.server_id, require_enabled=True)
    if server is None:
        raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")
    if not _gateway_url(server):
        raise HTTPException(status_code=503, detail="Gateway agent is not configured")

    old_public_key = record.client_public_key
    new_public_key = rotation.client_public_key
    client_address = record.client_address
    _rotate_peer(server, old_public_key, new_public_key, client_address)

    try:
        DEVICE_STORE.update(
            device_id=device_id,
            client_public_key=new_public_key,
            app_version=rotation.app_version,
            last_seen_at=_utc_now().isoformat(),
            provisioned=True,
        )
    except Exception as exc:
        try:
            _provision_peer(server, old_public_key, client_address)
            _revoke_peer(server, new_public_key)
        except Exception as rollback_error:
            raise HTTPException(
                status_code=502,
                detail="Device state update failed and gateway rollback also failed",
            ) from rollback_error
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=503, detail="Device state update failed; rotation rolled back") from exc

    updated = _load_record(device_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Device state could not be loaded after rotation")

    return DeviceRotationResponse(
        status="rotated",
        device_id=updated.device_id,
        client_address=updated.client_address,
        provisioned=updated.provisioned,
        server=server,
    )


@app.post("/v1/devices/{device_id}/migrate", response_model=DeviceMigrationResponse)
def migrate_device_server(
    request: Request,
    device_id: str,
    migration: DeviceMigrationRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_device_token: Annotated[str | None, Header()] = None,
) -> DeviceMigrationResponse:
    _enforce_production_transport_security(request)
    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    is_admin = False
    if authorization is not None:
        _require_admin_auth(authorization)
        is_admin = True
    else:
        _require_device_auth(record, x_device_token)

    target_server = _get_catalog_server(migration.target_server_id, require_enabled=False)
    if target_server is None:
        raise HTTPException(status_code=404, detail="Target VPN server not found")
    if not target_server.enabled:
        raise HTTPException(status_code=503, detail="Target VPN server is disabled")
    if target_server.tier == "premium" and record.tier != "premium" and not is_admin:
        raise HTTPException(status_code=403, detail="Premium tier is required for the target VPN server")

    previous_server_id = record.server_id
    if target_server.id == previous_server_id:
        if _gateway_url(target_server):
            _provision_peer(target_server, record.client_public_key, record.client_address)
            if not record.provisioned:
                DEVICE_STORE.update(
                    device_id=device_id,
                    last_seen_at=_utc_now().isoformat(),
                    provisioned=True,
                )
                record = _load_record(device_id) or record
        return DeviceMigrationResponse(
            status="unchanged",
            device_id=record.device_id,
            previous_server_id=previous_server_id,
            client_address=record.client_address,
            provisioned=record.provisioned,
            server=_server_with_health(target_server),
        )

    checked_target = _server_with_health(target_server)
    if _gateway_url(checked_target) is not None and checked_target.health_status != "ok":
        raise HTTPException(
            status_code=503,
            detail=f"Target VPN server '{target_server.id}' is currently {checked_target.health_status}",
        )
    if (checked_target.capacity_remaining or 0) <= 0:
        raise HTTPException(
            status_code=503,
            detail=f"Target VPN server '{target_server.id}' has reached its peer capacity",
        )

    try:
        new_client_address = DEVICE_STORE.allocate_address_for_server(
            server_id=target_server.id,
            vpn_address_pool=target_server.vpn_address_pool,
            vpn_gateway_address=target_server.vpn_gateway_address,
            peer_capacity=target_server.configured_peer_capacity,
            exclude_device_id=device_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    target_provisioned = False
    if _gateway_url(target_server):
        _provision_peer(target_server, record.client_public_key, new_client_address)
        DEVICE_STORE.remove_tombstone(target_server.id, record.client_public_key)
        target_provisioned = True

    old_server = _get_catalog_server(previous_server_id, require_enabled=False)
    old_client_address = record.client_address
    try:
        DEVICE_STORE.update(
            device_id=device_id,
            server_id=target_server.id,
            client_address=new_client_address,
            app_version=migration.app_version or record.app_version,
            last_seen_at=_utc_now().isoformat(),
            provisioned=target_provisioned,
        )
    except Exception as exc:
        if target_provisioned and _gateway_url(target_server):
            try:
                _revoke_peer(target_server, record.client_public_key)
            except Exception:
                DEVICE_STORE.add_tombstone(target_server.id, record.client_public_key, new_client_address)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=503, detail="Failed to persist server migration") from exc

    if old_server is not None and record.provisioned and _gateway_url(old_server):
        try:
            _revoke_peer(old_server, record.client_public_key)
        except Exception:
            # Record a durable tombstone so the source gateway cleans up the migrated peer on next reconciliation.
            DEVICE_STORE.add_tombstone(old_server.id, record.client_public_key, old_client_address)

    updated = _load_record(device_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Device state could not be loaded after migration")

    return DeviceMigrationResponse(
        status="migrated",
        device_id=updated.device_id,
        previous_server_id=previous_server_id,
        client_address=updated.client_address,
        provisioned=updated.provisioned,
        server=_server_with_health(target_server),
        tier=updated.tier,
    )


@app.post("/v1/devices/{device_id}/tier", response_model=DeviceTierUpdateResponse)
def update_device_tier(
    request: Request,
    device_id: str,
    payload: DeviceTierUpdateRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_device_token: Annotated[str | None, Header()] = None,
) -> DeviceTierUpdateResponse:
    _enforce_production_transport_security(request)
    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if authorization is not None:
        _require_admin_auth(authorization)
    else:
        _require_device_auth(record, x_device_token)
        if payload.tier == "premium":
            expected_receipt_secret = os.getenv("TUNNELPILOT_BILLING_VERIFY_SECRET")
            if ENVIRONMENT == "production" and not expected_receipt_secret:
                raise HTTPException(
                    status_code=503,
                    detail="Play Billing verification is not configured on control plane",
                )
            if expected_receipt_secret:
                if not payload.purchase_token or not hmac.compare_digest(
                    payload.purchase_token, expected_receipt_secret
                ):
                    raise HTTPException(status_code=403, detail="Invalid or unverified purchase token")
            elif not payload.purchase_token or len(payload.purchase_token.strip()) < 8:
                raise HTTPException(status_code=403, detail="Valid purchase_token is required for premium upgrade")

    DEVICE_STORE.update(
        device_id=device_id,
        tier=payload.tier,
        last_seen_at=_utc_now().isoformat(),
    )
    updated = _load_record(device_id) or record
    return DeviceTierUpdateResponse(status="updated", device_id=updated.device_id, tier=updated.tier)


def _require_revocation_auth(
    record: DeviceRecord,
    authorization: str | None,
    device_token: str | None,
    *,
    force: bool = False,
) -> bool:
    if authorization is not None:
        _require_admin_auth(authorization)
        return True

    if (
        device_token
        and record.device_token_hash
        and hmac.compare_digest(record.device_token_hash, _token_hash(device_token))
    ):
        if force:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="force=true requires administrative Bearer token",
            )
        return False

    if force and not _has_configured_admin_token():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control plane admin token is not configured",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: requires admin Bearer token or valid X-Device-Token",
    )


@app.delete("/v1/devices/{device_id}", response_model=DeviceRevocationResponse)
def revoke_device(
    request: Request,
    device_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_device_token: Annotated[str | None, Header()] = None,
    force: bool = False,
) -> DeviceRevocationResponse:
    _enforce_production_transport_security(request)
    if authorization is None and x_device_token is None:
        if force and not _has_configured_admin_token():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Control plane admin token is not configured",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: requires admin Bearer token or valid X-Device-Token",
        )
    if authorization is not None:
        _require_admin_auth(authorization)

    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    _require_revocation_auth(record, authorization, x_device_token, force=force)

    server = _get_catalog_server(record.server_id, require_enabled=False)
    if server is None and not force:
        raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")

    if record.provisioned and server and _gateway_url(server):
        try:
            _revoke_peer(server, record.client_public_key)
            DEVICE_STORE.remove_tombstone(server.id, record.client_public_key)
        except Exception as exc:
            if not force:
                raise HTTPException(
                    status_code=502,
                    detail="Gateway peer removal failed. Use force=true to override.",
                ) from exc
            DEVICE_STORE.add_tombstone(server.id, record.client_public_key, record.client_address)

    DEVICE_STORE.delete(device_id)
    DEVICES.pop(device_id, None)
    return DeviceRevocationResponse(status="revoked", device_id=device_id)
