"""Auth models for local (self-hosted) username/password authentication.

``AUTH_MODE="local"`` instances keep exactly one administrator account: the
``auth_credentials`` collection holds at most one bcrypt credential, and the
session itself is an HS256 JWT in the ``gaia_session`` cookie.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.db.repositories.base import MongoDocument

ADMIN_CREDENTIAL_SLOT = "admin"


def _normalize_email(value: EmailStr) -> str:
    """Lowercase the whole address. ``EmailStr`` alone only normalizes the
    domain; without this, ``Admin@EXAMPLE.com`` and ``admin@example.com`` are
    two accounts."""
    return str(value).lower()


# Request-side email type: validated as RFC-ish email, stored/compared lowercase.
NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]


class LocalCredentialDocument(MongoDocument):
    """One row per local user in the ``auth_credentials`` collection.

    ``password_hash`` is a bcrypt hash (never the password). Self-host signup
    closes once any row exists, so this collection stays single-row in practice;
    every row carries the constant ``slot`` discriminator and a unique index on
    it enforces the singleton atomically (the registration race is decided by
    Mongo, not by a read-then-write in request code). The row is still keyed by
    ``user_id``, so a future multi-account mode only drops the index.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str
    password_hash: str
    # Constant registration-slot discriminator — see the unique index in
    # app/db/mongodb/indexes.py. Never set to anything else while self-host
    # remains single-admin.
    slot: str = ADMIN_CREDENTIAL_SLOT
    created_at: datetime | None = None


class LocalCredentialUpdate(BaseModel):
    """No in-app update path exists for credentials (a rotation writes a new
    document). The repository base requires an update model; ``extra="forbid"``
    keeps any future accidental update attempt loud."""

    model_config = ConfigDict(extra="forbid")


class SignupRequest(BaseModel):
    """Body of ``POST /api/v1/auth/signup`` — creates the instance admin."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    # Minimum length is part of the request contract; pydantic turns shorter
    # passwords into a 422 before any write happens.
    password: str = Field(min_length=8)
    name: str | None = Field(None, max_length=100)


class LoginRequest(BaseModel):
    """Body of ``POST /api/v1/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: str
