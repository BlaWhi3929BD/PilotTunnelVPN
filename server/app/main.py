from __future__ import annotations

import base64
import binascii
import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="TunnelPilot Control Plane", version="0.2.0")

CONTROL_PLANE_TOKEN = os.getenv("TUNNELPILOT_CONTROL_PLANE_TOKEN")


class Server(BaseModel):
    id: str
    region: str
    hostname: str
    public_key: str
    port: int = Field(default=51820, ge=1, le=65535)
    enabled: bool = True


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
    created_at: datetime
    last_seen_at: datetime


class DeviceRegistrationResponse(BaseModel):
    status: str
    device_id: str
    server: Server
    registered_at: datetime


SERVERS = [
    Server(
        id="dev-1",
        region="dev",
        hostname="replace-with-real-gateway",
        public_key="replace-with-gateway-public-key",
    )
]

# Development-only in-memory registry. Production must use durable storage.
DEVICES: dict[str, DeviceRecord] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_control_plane_auth(authorization: str | None) -> None:
    if CONTROL_PLANE_TOKEN is not None and authorization != f"Bearer {CONTROL_PLANE_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/servers", response_model=list[Server])
def list_servers() -> list[Server]:
    return [server for server in SERVERS if server.enabled]


@app.post("/v1/devices", response_model=DeviceRegistrationResponse)
def register_device(
    registration: DeviceRegistration,
    authorization: Annotated[str | None, Header()] = None,
) -> DeviceRegistrationResponse:
    _require_control_plane_auth(authorization)

    server = next((item for item in SERVERS if item.enabled), None)
    if server is None:
        raise HTTPException(status_code=503, detail="No VPN server is currently available")

    now = _utc_now()
    existing = DEVICES.get(registration.device_id)
    if existing is not None and existing.client_public_key != registration.client_public_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="device_id is already registered with a different public key",
        )

    created_at = existing.created_at if existing is not None else now
    DEVICES[registration.device_id] = DeviceRecord(
        device_id=registration.device_id,
        client_public_key=registration.client_public_key,
        app_version=registration.app_version,
        server_id=server.id,
        created_at=created_at,
        last_seen_at=now,
    )

    return DeviceRegistrationResponse(
        status="accepted",
        device_id=registration.device_id,
        server=server,
        registered_at=created_at,
    )
