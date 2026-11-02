from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.passkey import PASSKEY_NAME_MAX_CHARS

# At least one visible character (the text is then trimmed and checked on the server).
_NAME = Field(min_length=1, max_length=PASSKEY_NAME_MAX_CHARS, pattern=r"\S")


class PasskeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    backed_up: bool = Field(
        description="A synced passkey (e.g. iCloud Keychain): works on the owner's other devices."
    )
    transports: list[str]


class PasskeyListOut(BaseModel):
    enabled: bool = Field(
        description="False until WEBAUTHN_RP_ID and WEBAUTHN_ORIGINS are set on the server."
    )
    rp_id: str | None = Field(description="The domain passkeys are bound to.")
    max_passkeys: int
    passkeys: list[PasskeyOut]


class PasskeyOptionsOut(BaseModel):
    options: dict[str, Any] = Field(
        description=(
            "WebAuthn options for navigator.credentials.create()/get() in their JSON form "
            "(PublicKeyCredentialCreationOptionsJSON / PublicKeyCredentialRequestOptionsJSON; "
            "binary values base64url)."
        )
    )
    expires_in_seconds: int = Field(description="The challenge is single-use and dies after this.")


class PasswordConfirm(BaseModel):
    """The current password, for adding or deleting a passkey (wrong ones count toward the
    login lockout)."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)


class PasskeyRegisterVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any] = Field(
        description="RegistrationResponseJSON: the result of navigator.credentials.create()."
    )
    name: str = _NAME


class PasskeyRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = _NAME


class PasskeyLoginVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any] = Field(
        description="AuthenticationResponseJSON: the result of navigator.credentials.get()."
    )
