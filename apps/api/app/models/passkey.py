from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, LargeBinary, String, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.user import User

# Width of webauthn_credentials.name (also the API's limit for it).
PASSKEY_NAME_MAX_CHARS = 64


class WebAuthnCredential(UUIDPrimaryKey, Timestamps, Base):
    """A passkey of the owner (WebAuthn credential): sign in with Face ID / Touch ID.

    Only public data is stored: the credential id the authenticator chose and its public
    key. The private key never leaves the owner's device (or their password manager).
    """

    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Raw credential id (WebAuthn allows up to 1023 bytes). Never logged in full.
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    # COSE-encoded public key, as returned at registration.
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    # The authenticator's signature counter (uint32; synced passkeys keep it at 0).
    sign_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # How the browser can reach the authenticator ("internal", "hybrid", "usb"…).
    transports: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    name: Mapped[str] = mapped_column(String(PASSKEY_NAME_MAX_CHARS))
    # Authenticator model (AAGUID, all zeros when the device does not say).
    aaguid: Mapped[str] = mapped_column(String(36))
    # A synced passkey (e.g. iCloud Keychain) also works on the owner's other devices.
    backed_up: Mapped[bool] = mapped_column(Boolean, server_default=false())
    last_used_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(lazy="joined")
