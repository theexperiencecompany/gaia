"""Short-lived HMAC tokens that let sandbox code call the execute route.

Minted per bash invocation and delivered only into that command's process
env. The sandbox never holds user credentials; a token only names whose tools
the host may run, for a window bounded by the command's own timeout. Layered
limits on the route (budget, rate, audit) stand in for an approval gate — see
execute_client.py for the threat model.
"""

import base64
from datetime import UTC, datetime
import hashlib
import hmac

from pydantic import BaseModel, ValidationError

from app.config.settings import settings
from app.utils.errors import AppError


class SandboxExecuteClaims(BaseModel):
    user_id: str
    run_id: str
    stream_id: str | None = None
    # Which sandbox instance the token was minted for — audit correlation; the
    # route cannot verify network origin, so this is a record, not a check.
    sandbox_id: str | None = None
    exp: int


def _secret() -> bytes:
    secret: str | None = settings.SANDBOX_EXECUTE_TOKEN_SECRET
    if not secret:
        raise AppError(
            message="Sandbox execute tokens are not configured",
            why="SANDBOX_EXECUTE_TOKEN_SECRET is unset",
            fix="Set SANDBOX_EXECUTE_TOKEN_SECRET (min 32 chars) to enable code mode",
            status_code=503,
        )
    return secret.encode()


def _sign(payload: bytes) -> str:
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def mint_execute_token(
    user_id: str,
    run_id: str,
    *,
    stream_id: str | None = None,
    sandbox_id: str | None = None,
    ttl_seconds: int,
) -> str:
    claims = SandboxExecuteClaims(
        user_id=user_id,
        run_id=run_id,
        stream_id=stream_id,
        sandbox_id=sandbox_id,
        exp=int(datetime.now(UTC).timestamp()) + ttl_seconds,
    )
    payload = base64.urlsafe_b64encode(claims.model_dump_json().encode()).decode()
    return f"{payload}.{_sign(payload.encode())}"


def verify_execute_token(token: str) -> SandboxExecuteClaims:
    """Claims for a valid token; raises 401 AppError on any tamper/expiry."""
    invalid = AppError(
        message="Invalid sandbox execute token",
        why="signature mismatch, malformed payload, or expired",
        fix="Re-run the bash command; each run mints a fresh short-lived token",
        status_code=401,
    )
    payload, _, signature = token.partition(".")
    if not payload or not signature:
        raise invalid
    if not hmac.compare_digest(_sign(payload.encode()), signature):
        raise invalid
    try:
        claims = SandboxExecuteClaims.model_validate_json(base64.urlsafe_b64decode(payload))
    except (ValidationError, ValueError):
        raise invalid from None
    if claims.exp < int(datetime.now(UTC).timestamp()):
        raise invalid
    return claims
