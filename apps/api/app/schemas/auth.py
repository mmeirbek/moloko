from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

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
    address_as: str | None = Field(
        description="How moloko addresses the owner in every answer; null = no particular form."
    )


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


ProfileField = Literal["address_as", "display_name"]


class ProfileUpdate(BaseModel):
    """Only the fields sent are changed. Text is trimmed and whitespace collapsed; line
    breaks and other control characters are refused (422 invalid_profile_text); blank or
    null clears the field."""

    model_config = ConfigDict(extra="forbid")

    address_as: str | None = Field(
        default=None,
        description="Form of address, e.g. «Мейрбек Максатович»; at most ADDRESS_AS_MAX_CHARS.",
    )
    display_name: str | None = Field(default=None, description="At most 128 characters.")

    def changes(self) -> dict[ProfileField, str | None]:
        """The fields that were sent (a field left out stays as it is)."""
        sent = self.model_fields_set
        out: dict[ProfileField, str | None] = {}
        if "address_as" in sent:
            out["address_as"] = self.address_as
        if "display_name" in sent:
            out["display_name"] = self.display_name
        return out


class SessionSettingsOut(BaseModel):
    """How long sign-ins last. Bounds and default come from the server's settings."""

    model_config = ConfigDict(from_attributes=True)

    ttl_hours: int = Field(description="Effective lifetime of new sign-ins, in hours.")
    default_ttl_hours: int = Field(description="SESSION_TTL_HOURS: used when no own choice.")
    min_hours: int
    max_hours: int
    uses_default: bool = Field(description="True when no own choice is stored.")
    current_session_expires_at: datetime


class SessionSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_hours: StrictInt | None = Field(
        description="Hours between min_hours and max_hours; null = back to the default."
    )
    password: str = Field(min_length=1, max_length=1024)
