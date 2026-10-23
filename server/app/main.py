from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from .storage import DeviceStore

RECONCILE_ON_STARTUP = os.getenv("TUNNELPILOT_RECONCILE_ON_STARTUP", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENVIRONMENT = os.getenv("TUNNELPILOT_ENV", "development").strip().lower()
ALLOW_OPEN_REGISTRATION = os.getenv("TUNNELPILOT_ALLOW_OPEN_REGISTRATION", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALLOW_NONSTANDARD_WG_INTERFACE = os.getenv(
    "TUNNELPILOT_ALLOW_NONSTANDARD_WG_INTERFACE", "false"
).lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    _validate_runtime_configuration()
    if RECONCILE_ON_STARTUP:
        for server in SERVERS:
            if server.enabled and _gateway_url(server):
                try:
                    # Startup reconciliation is strictly non-destructive (prune_unknown=False).
                    _reconcile_server(server, dry_run=False, prune_unknown=False)
                except Exception:
                    pass
    yield


app = FastAPI(title="TunnelPilot Control Plane", version="0.6.0", lifespan=_lifespan)

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


def _is_valid_admin_token(authorization: str | None) -> bool:
    if not CONTROL_PLANE_TOKEN or not CONTROL_PLANE_TOKEN.strip() or not authorization:
        return False
    expected = f"Bearer {CONTROL_PLANE_TOKEN}"
    return hmac.compare_digest(authorization, expected)


def _require_admin_auth(authorization: str | None) -> None:
    if not CONTROL_PLANE_TOKEN or not CONTROL_PLANE_TOKEN.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control plane admin token is not configured",
        )
    if not _is_valid_admin_token(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _require_control_plane_auth(authorization: str | None) -> None:
    if CONTROL_PLANE_TOKEN is not None and CONTROL_PLANE_TOKEN.strip():
        if not _is_valid_admin_token(authorization):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        return
    if ENVIRONMENT == "production" and not ALLOW_OPEN_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control plane enrollment token is required in production unless TUNNELPILOT_ALLOW_OPEN_REGISTRATION=true",
        )


def _validate_runtime_configuration() -> None:
    if ENVIRONMENT != "production":
        return
    if not CONTROL_PLANE_TOKEN or not CONTROL_PLANE_TOKEN.strip():
        raise RuntimeError("TUNNELPILOT_CONTROL_PLANE_TOKEN must be configured in production")
    enabled_servers = [srv for srv in SERVERS if srv.enabled]
    if not enabled_servers:
        raise RuntimeError("At least one enabled VPN server is required in production")
    for srv in enabled_servers:
        if not _gateway_url(srv) or not GATEWAY_AGENT_TOKEN or not GATEWAY_AGENT_TOKEN.strip():
            raise RuntimeError(
                f"Gateway agent URL and token must be configured for server '{srv.id}' in production"
            )
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

    try:
        validated_rows = DEVICE_STORE.verify_integrity(
            vpn_address_pool=VPN_ADDRESS_POOL,
            vpn_gateway_address=VPN_GATEWAY_ADDRESS,
        )
        pool_network = ipaddress.ip_network(VPN_ADDRESS_POOL, strict=True)
        if not isinstance(pool_network, ipaddress.IPv4Network):
            raise RuntimeError("TUNNELPILOT_VPN_ADDRESS_POOL must be an IPv4 network")
    except (RuntimeError, ValueError) as exc:
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

    prunable_unknown: list[str] = []
    unmanaged_unknown: list[str] = []
    for unknown_key in sorted(active_peers - expected_map.keys()):
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
        return ServerReconcileReport(
            server_id=server.id,
            status="dry_run",
            dry_run=True,
            prune_unknown=prune_unknown,
            restored_peers=0,
            removed_peers=0,
            would_restore_peers=len(to_restore),
            would_remove_peers=len(prunable_unknown) if prune_unknown else 0,
            unknown_peers=len(prunable_unknown),
            unmanaged_peers=len(unmanaged_unknown),
        )

    restored = 0
    for public_key, client_address in to_restore:
        _provision_peer(server, public_key, client_address)
        restored += 1

    removed = 0
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


@app.post("/v1/servers/reconcile", response_model=list[ServerReconcileReport])
def reconcile_servers(
    authorization: Annotated[str | None, Header()] = None,
    dry_run: bool = False,
    prune_unknown: bool = False,
    confirm_empty_db: bool = False,
) -> list[ServerReconcileReport]:
    _require_admin_auth(authorization)
    enabled = [server for server in SERVERS if server.enabled]
    return [
        _reconcile_server(
            server,
            dry_run=dry_run,
            prune_unknown=prune_unknown,
            confirm_empty_db=confirm_empty_db,
        )
        for server in enabled
    ]


@app.post("/v1/servers/{server_id}/reconcile", response_model=ServerReconcileReport)
def reconcile_single_server(
    server_id: str,
    authorization: Annotated[str | None, Header()] = None,
    dry_run: bool = False,
    prune_unknown: bool = False,
    confirm_empty_db: bool = False,
) -> ServerReconcileReport:
    _require_admin_auth(authorization)
    server = next((item for item in SERVERS if item.id == server_id and item.enabled), None)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return _reconcile_server(
        server,
        dry_run=dry_run,
        prune_unknown=prune_unknown,
        confirm_empty_db=confirm_empty_db,
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

    try:
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
    )


@app.post("/v1/devices/{device_id}/rotate", response_model=DeviceRotationResponse)
def rotate_device_key(
    device_id: str,
    rotation: DeviceRotationRequest,
    x_device_token: Annotated[str | None, Header()] = None,
) -> DeviceRotationResponse:
    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    _require_device_auth(record, x_device_token)

    if rotation.client_public_key == record.client_public_key:
        server = next((item for item in SERVERS if item.id == record.server_id and item.enabled), None)
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

    server = next((item for item in SERVERS if item.id == record.server_id and item.enabled), None)
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


def _require_revocation_auth(
    record: DeviceRecord,
    authorization: str | None,
    device_token: str | None,
    *,
    force: bool = False,
) -> bool:
    if _is_valid_admin_token(authorization):
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

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: requires admin Bearer token or valid X-Device-Token",
    )


@app.delete("/v1/devices/{device_id}", response_model=DeviceRevocationResponse)
def revoke_device(
    device_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_device_token: Annotated[str | None, Header()] = None,
    force: bool = False,
) -> DeviceRevocationResponse:
    record = _load_record(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Device not found")

    _require_revocation_auth(record, authorization, x_device_token, force=force)

    server = next((item for item in SERVERS if item.id == record.server_id), None)
    if server is None and not force:
        raise HTTPException(status_code=503, detail="Assigned VPN server is unavailable")

    if record.provisioned and server and _gateway_url(server):
        try:
            _revoke_peer(server, record.client_public_key)
        except Exception as exc:
            if not force:
                raise HTTPException(
                    status_code=502,
                    detail="Gateway peer removal failed. Use force=true to override.",
                ) from exc

    DEVICE_STORE.delete(device_id)
    DEVICES.pop(device_id, None)
    return DeviceRevocationResponse(status="revoked", device_id=device_id)
