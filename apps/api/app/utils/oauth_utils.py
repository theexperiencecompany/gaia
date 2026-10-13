from urllib.parse import urlencode

from fastapi import HTTPException
import httpx
from pydantic import BaseModel, ConfigDict

from app.config.settings import settings
from app.config.token_repository import resolve_google_oauth_credentials, token_repository
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

http_async_client = httpx.AsyncClient()


class _GrantedScopes(BaseModel):
    """A stored OAuth token, read only for the scopes it already grants."""

    model_config = ConfigDict(extra="ignore")

    scope: str | None = None


async def build_google_oauth_url(
    user_email: str,
    state_token: str,
    integration_scopes: list[str],
    user_id: str | None = None,
) -> str:
    log.set(
        operation="build_google_oauth_url",
        user_email=user_email,
        requested_scopes=integration_scopes,
        user_id=user_id,
    )
    """
    Build a Google OAuth authorization URL with proper scope handling.

    Args:
        user_email: User's email for login hint
        state_token: OAuth state token for CSRF protection
        integration_scopes: New scopes to request for this integration
        user_id: Optional user ID to fetch existing scopes

    Returns:
        Complete Google OAuth authorization URL
    """
    # Base scopes always required
    base_scopes = ["openid", "profile", "email"]

    # Get existing scopes from user's current token
    existing_scopes: list[str] = []
    if user_id:
        try:
            token = await token_repository.get_token(str(user_id), "google", renew_if_expired=False)
            if token:
                existing_scopes = (_GrantedScopes.model_validate(token).scope or "").split()
        except Exception as e:
            log.debug(
                f"{LogTag.OAUTH} Could not get existing scopes for user",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    # Combine all scopes (base + existing + new), removing duplicates
    all_scopes = list(set(base_scopes + existing_scopes + integration_scopes))

    # Credentials resolve store-first; without both halves there is no valid
    # authorization URL to build.
    credentials = await resolve_google_oauth_credentials()
    if credentials is None:
        log.error(f"{LogTag.OAUTH} Google OAuth is not configured; cannot build authorize URL")
        raise HTTPException(
            status_code=503,
            detail="Google integration is not configured on this instance.",
        )
    client_id, _ = credentials

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": settings.GOOGLE_CALLBACK_URL,
        "scope": " ".join(all_scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "login_hint": user_email,
        "state": state_token,
    }
    return f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
