"""How moloko addresses the owner (``users.address_as``, e.g. «Мейрбек Максатович»).

* Input (API ``PATCH /auth/profile`` and the CLI) goes through ``normalize_profile_text``:
  leading/trailing whitespace trimmed, inner runs of whitespace collapsed to one space,
  control and invisible formatting characters (line breaks, tabs, bidi overrides,
  zero-width characters) rejected with 422, empty → NULL, at most
  ``ADDRESS_AS_MAX_CHARS``.
* Prompts get it only through ``address_instruction``: one quoted line in the
  *instruction* part of the chat, agent-run and Orchestrator system prompts. This is
  allowed because it is the owner's own setting (not memory, not tool or web text);
  memory still goes only through ``app.memory.context``.
"""

from __future__ import annotations

import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.user import DISPLAY_NAME_MAX_CHARS, User

# Unicode categories never allowed in a profile text: control (Cc: line breaks, tabs…),
# format (Cf: bidi overrides, zero-width characters), surrogates, private use, and the
# line/paragraph separators.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


__all__ = [
    "DISPLAY_NAME_MAX_CHARS",
    "InvalidProfileText",
    "ProfileTextTooLong",
    "address_instruction",
    "normalize_profile_text",
    "owner_address_instruction",
]


class InvalidProfileText(AppError):
    status_code = 422
    code = "invalid_profile_text"
    message = "Use one line of text without control or invisible characters."


class ProfileTextTooLong(AppError):
    status_code = 422
    code = "profile_text_too_long"
    message = "This text is too long."


def _forbidden(ch: str) -> bool:
    return unicodedata.category(ch) in _FORBIDDEN_CATEGORIES


def normalize_profile_text(value: str | None, *, field: str, max_chars: int) -> str | None:
    """One clean line, or ``None`` for "not set". Raises 422 errors naming ``field``."""
    if value is None:
        return None
    if any(_forbidden(ch) for ch in value):
        raise InvalidProfileText(details={"field": field})
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > max_chars:
        raise ProfileTextTooLong(
            f"At most {max_chars} characters.", details={"field": field, "max": max_chars}
        )
    return text


def address_instruction(address_as: str | None) -> str:
    """The system-prompt line that makes every answer use the owner's form of address.

    ``""`` when none is set. Stored values are already normalised; this keeps the line
    a single line and the quotation closed even for a value written before a rule
    changed (« and » inside the value become plain double quotes).
    """
    if not address_as:
        return ""
    text = " ".join("".join(" " if _forbidden(ch) else ch for ch in address_as).split())
    text = text.replace("«", '"').replace("»", '"')
    if not text:
        return ""
    return (
        f"Always address the owner as «{text}» — exactly this form, whatever language you reply in."
    )


async def owner_address_instruction(db: AsyncSession, user_id: uuid.UUID) -> str:
    """``address_instruction`` for this user (``""`` when none is set)."""
    address_as = (
        await db.execute(select(User.address_as).where(User.id == user_id))
    ).scalar_one_or_none()
    return address_instruction(address_as)
