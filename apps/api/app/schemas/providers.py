from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ProviderKindLiteral = Literal["openai", "anthropic", "mock"]


def _check_base_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not value.startswith("https://") or len(value) > 512:
        raise ValueError("base_url must be an https:// URL")
    return value.rstrip("/")


class ProviderOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    base_url: str | None
    enabled: bool
    api_key_source: Literal["stored", "environment", "none"]
    api_key_hint: str | None
    created_at: datetime


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProviderKindLiteral
    name: str = Field(min_length=1, max_length=64)
    api_key: SecretStr | None = None
    base_url: str | None = None
    enabled: bool = True

    _base_url = field_validator("base_url")(_check_base_url)


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    base_url: str | None = None
    enabled: bool | None = None

    _base_url = field_validator("base_url")(_check_base_url)


class ProviderTestResult(BaseModel):
    ok: bool
    models_found: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class SyncModelsResult(BaseModel):
    added: int
    total: int


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    provider_name: str
    provider_kind: str
    model: str
    display_name: str | None
    enabled: bool
    is_default: bool
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    params: dict[str, Any]


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)


class ModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: uuid.UUID
    model: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


class ModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    is_default: bool | None = None
    input_price_per_mtok: Decimal | None = Field(default=None, ge=0)
    output_price_per_mtok: Decimal | None = Field(default=None, ge=0)
    params: ModelParams | None = None
