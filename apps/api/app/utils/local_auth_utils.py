"""Local-auth session tokens for self-hosting.

A session is an HS256 JWT signed with the per-instance secret, carried in
the gaia session cookie as the twin of the WorkOS sealed-session cookie.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import NamedTuple, TypedDict, cast

from jose import JWTError, jwt

from app.constants.auth import JWT_ALGORITHM
from app.constants.log_tags import LogTag
from app.db.repositories.local_credentials import local_credentials_repository
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser
from app.services.runtime.secrets_store import get_instance_secret
from app.utils.auth_utils import build_user_context
from shared.py.wide_events import log

LOCAL_SESSION_COOKIE = "gaia_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600

# Cached once per process so a request does not await Mongo for it; tests
# reset this attribute directly.
_resolved_secret: str | None = None


class SessionClaims(TypedDict, total=False):
    """The local-session JWT claims this module reads.

    Sub carries the user id and ver the password-bumpable token version, so a
    bump stops every older session verifying.
    """

    sub: str
    ver: int


async def _session_secret() -> str:
    """Resolve the signing secret once per process (env override or Mongo)."""
    global _resolved_secret
    if _resolved_secret is None:
        _resolved_secret = await get_instance_secret()
    return _resolved_secret


async def issue_session_token(user_id: str, token_version: int) -> str:
    """Mint a session JWT for a user id, valid for the session TTL.

    The version embeds as ver and is checked on every request, so bumping it
    invalidates prior tokens; legacy tokens without ver read as zero.
    """
    secret = await _session_secret()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "exp": now + timedelta(seconds=SESSION_TTL_SECONDS),
        "iat": now,
        "ver": token_version,
    }
    return cast(str, jwt.encode(payload, secret, algorithm=JWT_ALGORITHM))


class _Session(NamedTuple):
    """Who a verified token names, and the token version it carries."""

    user_id: str
    version: int


def _decode_session(token: str, secret: str) -> _Session | None:
    """Return the session of a validly signed, unexpired token naming a user, else None."""
    try:
        claims: SessionClaims = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    sub = claims.get("sub")
    # Legacy tokens without ver read as 0.
    return _Session(str(sub), claims.get("ver", 0)) if sub else None


async def resolve_session_token(token: str) -> str | None:
    """Warm the secret cache, then verify a request-path token.

    Returns the user id, or None for an invalid, expired, or revoked token.
    """
    session = _decode_session(token, await _session_secret())
    if session is None:
        return None
    user_id = session.user_id
    # Version check — stateless JWTs are revoked by bumping
    # auth_credentials.token_version on password change.
    try:
        token_ver_int = int(session.version)
    except (TypeError, ValueError):
        return None
    # Credential lookup is the revocation source.
    try:
        credential = await local_credentials_repository.get_by_user_id(user_id)
    except Exception as exc:
        # DB unavailable must not turn a revoked token valid. For legacy
        # ver-0 tokens we keep the old behaviour (they pre-date the version
        # field and may exist before any credential row), otherwise fail closed.
        log.warning(
            "local session version check failed — DB unavailable",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return user_id if token_ver_int == 0 else None
    if credential is None:
        # No credential row: only honour legacy ver 0 tokens (pre-migration).
        return user_id if token_ver_int == 0 else None
    if credential.disabled_at is not None:
        return None
    if token_ver_int != credential.token_version:
        return None
    return user_id


class LocalSessionFailure(StrEnum):
    """Which step refused a local session token."""

    INVALID_OR_EXPIRED = "invalid_or_expired_session"
    UNKNOWN_USER = "unknown_local_session_user"


async def authenticate_local_session(token: str) -> AuthenticatedUser | LocalSessionFailure:
    """Resolve a local session token to its account, for the HTTP middleware and WebSockets alike.

    A verification or lookup error is logged and refuses the token: a broken
    secret store must surface, never pass as a session or crash the caller.
    """
    try:
        user_id = await resolve_session_token(token)
    except Exception as e:
        log.error(
            f"{LogTag.API} local session verification error",
            auth_failure=type(e).__name__,
            error=str(e),
        )
        user_id = None
    if not user_id:
        return LocalSessionFailure.INVALID_OR_EXPIRED

    try:
        user_data = await user_repository.get(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.API} Invalid user_id in local session token",
            error_type=type(e).__name__,
            error=str(e),
        )
        user_data = None
    if user_data is None:
        return LocalSessionFailure.UNKNOWN_USER
    return build_user_context(user_data, auth_provider="email")
