from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .wireguard import normalize_allowed_ip, validate_public_key


class PeerCreateRequest(BaseModel):
    public_key: str = Field(min_length=40, max_length=64)
    allowed_ip: str = Field(min_length=9, max_length=64)

    @field_validator("public_key")
    @classmethod
    def validate_public_key_value(cls, value: str) -> str:
        return validate_public_key(value)

    @field_validator("allowed_ip")
    @classmethod
    def validate_allowed_ip_value(cls, value: str) -> str:
        return normalize_allowed_ip(value)


class PeerResponse(BaseModel):
    status: str
    public_key: str
    allowed_ip: str


class GatewayHealthResponse(BaseModel):
    status: str
    interface: str
    wireguard_available: bool
