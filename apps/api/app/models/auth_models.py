"""Auth models for local (self-hosted) username/password authentication.

``AUTH_MODE="local"`` instances keep exactly one administrator account: the
``auth_credentials`` collection holds at most one bcrypt credential, and the
session itself is an HS256 JWT in the ``gaia_session`` cookie.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.db.repositories.base import MongoDocument

ADMIN_CREDENTIAL_SLOT = "admin"

# bcrypt hashes at most the first 72 BYTES of a password, and bcrypt >= 5
# raises ValueError past that instead of silently truncating. The limit is
# enforced on the wire so an oversized password is a clean 422 before any row
# is written. Chars are not bytes: multibyte characters blow past the cap far
# below 72 characters.
BCRYPT_MAX_PASSWORD_BYTES = 72


def _reject_over_bcrypt_limit(value: str) -> str:
    """Refuse passwords whose UTF-8 encoding exceeds bcrypt's input cap."""
    if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
        )
    return value


# Byte-level cap as a reusable type: Field(max_length=...) counts characters,
# so this validator is what actually guarantees bcrypt can hash the value.
BcryptLimitedPassword = Annotated[
    str,
    StringConstraints(max_length=BCRYPT_MAX_PASSWORD_BYTES),
    AfterValidator(_reject_over_bcrypt_limit),
]


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
    """Typed update payload for credential writes. The bcrypt hash is the ONLY
    mutable field (the password-change endpoint rotates it); ``user_id``,
    ``slot`` and ``created_at`` are write-once identity. ``extra="forbid"``
    keeps any accidental extra-field update loud."""

    model_config = ConfigDict(extra="forbid")

    password_hash: str


class SignupRequest(BaseModel):
    """Body of ``POST /api/v1/auth/signup`` — creates the instance admin."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    # Minimum length is part of the request contract; pydantic turns shorter
    # passwords into a 422 before any write happens. The upper bound is
    # bcrypt's hard input cap — see BcryptLimitedPassword.
    password: BcryptLimitedPassword = Field(min_length=8)
    name: str | None = Field(None, max_length=100)


class LoginRequest(BaseModel):
    """Body of ``POST /api/v1/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    # Same byte cap as signup: bcrypt >= 5 raises ValueError verifying a
    # longer password, which would surface as a 500 instead of the uniform
    # 401. (No min_length here — login must not reject credentials created
    # under older policy.)
    password: BcryptLimitedPassword


class ChangePasswordRequest(BaseModel):
    """Body of ``PATCH /api/v1/auth/password`` — rotates the caller's own
    password after re-verifying the current one."""

    model_config = ConfigDict(extra="forbid")

    current_password: BcryptLimitedPassword
    # Same contract as SignupRequest.password: minimum length on the wire,
    # byte-level cap guaranteed by BcryptLimitedPassword.
    new_password: BcryptLimitedPassword = Field(min_length=8)
