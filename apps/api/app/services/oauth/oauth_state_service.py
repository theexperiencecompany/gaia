"""
OAuth State Management Service.

Provides secure state token management for OAuth flows to prevent:
- Open redirect vulnerabilities
- CSRF attacks
- XSS attacks

Uses Redis for temporary state storage with automatic expiration.
"""

import secrets

from app.constants.cache import STATE_KEY_PREFIX, STATE_TOKEN_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import OAuthContext, log


async def create_oauth_state(user_id: str, redirect_path: str, integration_id: str) -> str:
    """Create a secure state token for OAuth flow, stored in Redis with expiration.

    Uses a 32-byte cryptographically secure random token and validates the
    redirect path against an allowlist.
    """
    log.set(
        auth={"user_id": user_id, "provider": integration_id},
        oauth=OAuthContext(operation="authorize", integration_id=integration_id),
    )

    # Validate redirect path - only allow safe paths
    if not is_safe_redirect_path(redirect_path):
        log.warning(
            f"{LogTag.OAUTH} Unsafe redirect path rejected for user",
            user_id=user_id,
            redirect_path=redirect_path,
            integration_id=integration_id,
        )
        # Default to safe path
        redirect_path = "/c"

    # Generate cryptographically secure random token
    state_token = secrets.token_urlsafe(32)

    # Store state in Redis with expiration
    redis_client = redis_cache.client
    state_key = f"{STATE_KEY_PREFIX}:{state_token}"

    state_data = {
        "user_id": user_id,
        "redirect_path": redirect_path,
        "integration_id": integration_id,
    }

    await redis_client.hset(state_key, mapping=state_data)
    await redis_client.expire(state_key, STATE_TOKEN_TTL)

    log.info(
        f"{LogTag.OAUTH} Created OAuth state token",
        user_id=user_id,
        integration_id=integration_id,
    )
    return state_token


async def validate_and_consume_oauth_state(
    state_token: str,
) -> dict[str, str] | None:
    """Validate an OAuth state token and delete it to prevent replay, or return None.

    Returns user_id, redirect_path, and integration_id when valid.
    """
    try:
        redis_client = redis_cache.client
        state_key = f"{STATE_KEY_PREFIX}:{state_token}"

        # Get state data
        state_data = await redis_client.hgetall(state_key)

        if not state_data:
            log.warning(f"{LogTag.OAUTH} Invalid or expired OAuth state token")
            return None

        # Decode bytes to strings
        result = {
            "user_id": state_data.get("user_id", ""),
            "redirect_path": state_data.get("redirect_path", ""),
            "integration_id": state_data.get("integration_id", ""),
        }

        log.set(auth={"user_id": result["user_id"], "provider": result["integration_id"]})
        log.set_ns("oauth", operation="callback", integration_id=result["integration_id"])

        # Validate that we have all required fields
        if not all([result["user_id"], result["redirect_path"], result["integration_id"]]):
            log.warning(f"{LogTag.OAUTH} Incomplete OAuth state data for token")
            return None

        # Delete the token to prevent replay attacks
        await redis_client.delete(state_key)

        log.info(
            f"{LogTag.OAUTH} OAuth state validated and consumed",
            user_id=result["user_id"],
            integration_id=result["integration_id"],
        )
        return result

    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Error validating OAuth state",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


def is_safe_redirect_path(path: str) -> bool:
    """Return True if path is a safe relative redirect (no protocol-relative or traversal tricks)."""
    if not path:
        return False

    # Must start with /
    if not path.startswith("/"):
        return False

    # Reject backslashes — some browsers normalize `\` to `/`,
    # making `/\evil.com` behave like a protocol-relative URL.
    if "\\" in path:
        return False

    lower_path = path.lower()

    # Must not contain // anywhere (protocol-relative or absolute URL indicator).
    # Also reject the URL-encoded form which downstream layers may decode.
    if "//" in path or "%2f%2f" in lower_path or "%5c" in lower_path:
        return False

    # Must not contain any URL protocols (http:, https:, ftp:, etc.)
    dangerous_protocols = [
        "http:",
        "https:",
        "ftp:",
        "ftps:",
        "javascript:",
        "data:",
        "vbscript:",
        "file:",
        "ws:",
        "wss:",
    ]
    if any(proto in lower_path for proto in dangerous_protocols):
        return False

    # Must not contain path traversal
    if ".." in path:
        return False

    # Must not contain @ (could indicate user:pass@domain)
    return "@" not in path
