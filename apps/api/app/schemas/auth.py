from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Usernames are created only through the CLI; login accepts any string so the
# response never reveals the format rules.
USERNAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{2,63}$"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str | None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    session: SessionOut


class CsrfResponse(BaseModel):
    csrf_token: str
