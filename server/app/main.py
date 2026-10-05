from __future__ import annotations

import os
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="TunnelPilot Control Plane", version="0.1.0")

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
    client_public_key: str = Field(min_length=20, max_length=64)
    app_version: str = Field(min_length=1, max_length=32)


SERVERS = [
    Server(
        id="dev-1",
        region="dev",
        hostname="replace-with-real-gateway",
        public_key="replace-with-gateway-public-key",
    )
]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/servers", response_model=list[Server])
def list_servers() -> list[Server]:
    return [server for server in SERVERS if server.enabled]


@app.post("/v1/devices")
def register_device(
    registration: DeviceRegistration,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    if CONTROL_PLANE_TOKEN is not None and authorization != f"Bearer {CONTROL_PLANE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "status": "accepted",
        "device_id": registration.device_id,
        "message": "Provisioning is intentionally disabled in this development control plane.",
    }
