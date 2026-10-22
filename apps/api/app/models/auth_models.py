"""Auth models for local (self-hosted) username/password authentication.

AUTH_MODE="local" instances hold one bcrypt credential per account in
auth_credentials (the first account administers the instance), invite links in
auth_invites, and the session itself is an HS256 JWT in the gaia_session cookie.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.constants.auth import MIN_PASSWORD_LENGTH
from app.db.repositories.base import MongoDocument

ADMIN_CREDENTIAL_SLOT = "admin"

# bcrypt hashes at most the first 72 BYTES of a password, and bcrypt >= 5
# raises ValueError past that instead of silently truncating. Enforced on the
# wire so an oversized password is a clean 422 before any row is written.
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
    """One row per local user in the auth_credentials collection.

    password_hash is a bcrypt hash, never the password. Only the first account's
    row carries slot=admin; a partial unique index on slot makes that bootstrap
    claim atomic. disabled_at marks an account an administrator removed.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str
    password_hash: str
    slot: str | None = None
    # Monotonic session revocation counter. Embedded as ``ver`` in the JWT;
    # bumping it (e.g. on password change) invalidates all previously issued
    # tokens whose ``ver`` no longer matches.
    token_version: int = 0
    disabled_at: datetime | None = None
    created_at: datetime | None = None


class LocalCredentialUpdate(BaseModel):
    """Typed update payload for credential writes; user_id, slot and created_at are write-once."""

    model_config = ConfigDict(extra="forbid")

    password_hash: str | None = None
    token_version: int | None = None
    disabled_at: datetime | None = None


class LocalInviteDocument(MongoDocument):
    """A single-use self-host invite link in auth_invites; only the token's SHA-256 is stored."""

    model_config = ConfigDict(extra="ignore")

    token_hash: str
    created_by: str
    expires_at: datetime
    used_at: datetime | None = None
    used_by: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


class LocalInviteUpdate(BaseModel):
    """Typed update payload for an invite; only the redeemer is set after redemption."""

    model_config = ConfigDict(extra="forbid")

    used_by: str | None = None


class SignupRequest(BaseModel):
    """Body of POST /api/v1/auth/signup; invite is the token from an invite link."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    # Minimum length is part of the request contract; pydantic turns shorter
    # passwords into a 422 before any write happens. The upper bound is
    # bcrypt's hard input cap — see BcryptLimitedPassword.
    password: BcryptLimitedPassword = Field(min_length=MIN_PASSWORD_LENGTH)
    name: str | None = Field(None, max_length=100)
    invite: str | None = Field(None, min_length=1, max_length=128)


class LoginRequest(BaseModel):
    """Body of ``POST /api/v1/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    # Same byte cap as signup: bcrypt >= 5 raises ValueError verifying a longer
    # password, which would surface as a 500 instead of the uniform 401.
    # (No min_length here: login must accept older-policy credentials.)
    password: BcryptLimitedPassword


class ChangePasswordRequest(BaseModel):
    """Body of ``PATCH /api/v1/auth/password`` — rotates the caller's own
    password after re-verifying the current one."""

    model_config = ConfigDict(extra="forbid")

    current_password: BcryptLimitedPassword
    # Same contract as SignupRequest.password: minimum length on the wire,
    # byte-level cap guaranteed by BcryptLimitedPassword.
    new_password: BcryptLimitedPassword = Field(min_length=MIN_PASSWORD_LENGTH)
