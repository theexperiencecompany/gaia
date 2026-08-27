"""Local-auth session tokens (``AUTH_MODE="local"``, self-hosting).

A session is an HS256 JWT signed with the per-instance secret (see
``app.services.runtime.secrets_store``), carried in the ``gaia_session`` cookie
— the self-host twin of the WorkOS sealed-session cookie. The jose usage
mirrors ``app/api/v1/middleware/agent_auth.py``.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

from jose import JWTError, jwt

from app.constants.auth import JWT_ALGORITHM
from app.db.repositories.local_credentials import local_credentials_repository
from app.services.runtime.secrets_store import get_instance_secret
from shared.py.wide_events import log

LOCAL_SESSION_COOKIE = "gaia_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600

# The instance secret is immutable for the life of an instance, so it is read
# once per process and cached here: verify_session_token is sync by contract
# (the middleware dispatch path is hot) and cannot await Mongo on every call.
# Tests reset this attribute; production never has a reason to.
_resolved_secret: str | None = None


async def _session_secret() -> str:
    """Resolve the signing secret once per process (env override or Mongo)."""
    global _resolved_secret
    if _resolved_secret is None:
        _resolved_secret = await get_instance_secret()
    return _resolved_secret


async def issue_session_token(user_id: str, token_version: int = 0) -> str:
    """Mint a session JWT naming ``user_id``, valid for SESSION_TTL_SECONDS.

    ``token_version`` is embedded as ``ver`` and checked against
    ``auth_credentials.token_version`` on every request — bumping the stored
    version (e.g. on password change) invalidates all previously issued JWTs.
    Legacy tokens without ``ver`` are treated as 0 for backwards compat.
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


def verify_session_token(token: str) -> str | None:
    """The ``sub`` of a valid, unexpired token, else ``None``.

    Raises RuntimeError when the secret was never resolved in this process —
    that is a caller bug (go through :func:`resolve_session_token`), not an
    invalid session: silently returning ``None`` here would log every existing
    user out after each restart until their next login, invisibly.
    """
    if _resolved_secret is None:
        raise RuntimeError(
            "local session secret not resolved — await resolve_session_token() "
            "before calling verify_session_token()"
        )
    try:
        payload = jwt.decode(token, _resolved_secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


async def resolve_session_token(token: str) -> str | None:
    """Async entry point for request paths: warms the secret cache, then
    verifies. Returns the user id, or ``None`` for an invalid/expired/tampered
    token or a revoked version (``ver`` mismatch)."""
    await _session_secret()
    user_id = verify_session_token(token)
    if user_id is None:
        return None
    # Version check — stateless JWTs are revoked by bumping
    # auth_credentials.token_version on password change. Legacy tokens without
    # ``ver`` are treated as 0.
    try:
        payload = jwt.decode(token, _resolved_secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    token_ver = payload.get("ver", 0)
    try:
        token_ver_int = int(token_ver)
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
    current_ver = int(getattr(credential, "token_version", 0) or 0)
    if token_ver_int != current_ver:
        return None
    return user_id
