"""
OAuth State Management Service

Provides secure state token management for OAuth flows to prevent:
- Open redirect vulnerabilities
- CSRF attacks
- XSS attacks

Uses Redis for temporary state storage with automatic expiration.
"""

import secrets

from app.constants.cache import STATE_KEY_PREFIX, STATE_TOKEN_TTL
from app.db.redis import redis_cache
from shared.py.wide_events import log


async def create_oauth_state(user_id: str, redirect_path: str, integration_id: str) -> str:
    """
    Create a secure state token for OAuth flow.

    Args:
        user_id: The user ID initiating the OAuth flow
        redirect_path: The frontend path to redirect to after OAuth completes
        integration_id: The integration being connected

    Returns:
        A secure random state token

    Security:
        - Uses cryptographically secure random token (32 bytes = 256 bits)
        - Stores state server-side with automatic expiration
        - Validates redirect path against allowlist
    """
    log.set(auth={"user_id": user_id, "provider": integration_id})

    # Validate redirect path - only allow safe paths
    if not is_safe_redirect_path(redirect_path):
        log.warning(f"Unsafe redirect path rejected for user {user_id}: {redirect_path}")
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

    await redis_client.hset(state_key, mapping=state_data)  # type: ignore[arg-type]
    await redis_client.expire(state_key, STATE_TOKEN_TTL)

    log.info(f"Created OAuth state token for user {user_id}, integration {integration_id}")
    return state_token


async def validate_and_consume_oauth_state(
    state_token: str,
) -> dict[str, str] | None:
    """
    Validate and consume an OAuth state token.

    Args:
        state_token: The state token to validate

    Returns:
        Dictionary containing user_id, redirect_path, and integration_id if valid,
        None if invalid or expired

    Security:
        - Token is consumed (deleted) after validation to prevent replay attacks
        - Returns None for invalid/expired tokens
    """
    try:
        redis_client = redis_cache.client
        state_key = f"{STATE_KEY_PREFIX}:{state_token}"

        # Get state data
        state_data = await redis_client.hgetall(state_key)

        if not state_data:
            log.warning(f"Invalid or expired OAuth state token: {state_token}")
            return None

        # Decode bytes to strings
        result = {
            "user_id": state_data.get("user_id", ""),
            "redirect_path": state_data.get("redirect_path", ""),
            "integration_id": state_data.get("integration_id", ""),
        }

        log.set(auth={"user_id": result["user_id"], "provider": result["integration_id"]})

        # Validate that we have all required fields
        if not all([result["user_id"], result["redirect_path"], result["integration_id"]]):
            log.warning(f"Incomplete OAuth state data for token: {state_token}")
            return None

        # Delete the token to prevent replay attacks
        await redis_client.delete(state_key)

        log.info(
            f"OAuth state validated and consumed for user {result['user_id']}, "
            f"integration {result['integration_id']}"
        )
        return result

    except Exception as e:
        log.error(f"Error validating OAuth state: {e}")
        return None


def is_safe_redirect_path(path: str) -> bool:
    """
    Validate that a redirect path is safe.

    Args:
        path: The path to validate

    Returns:
        True if the path is safe, False otherwise

    Security checks:
        - No absolute URLs (must be relative paths)
        - No protocol-relative URLs (//example.com or /\\example.com)
        - Must start with /
        - No javascript: or data: URLs
        - No path traversal attempts
    """
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
    if "@" in path:
        return False

    return True
