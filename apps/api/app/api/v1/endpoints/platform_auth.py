from typing import Callable, Optional
from urllib.parse import urlencode

import httpx
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.services.platform_link_service import PlatformLinkService
from fastapi import APIRouter
from fastapi.responses import RedirectResponse


class PlatformOAuthConfig:
    """Configuration for platform-specific OAuth flows."""

    def __init__(
        self,
        platform: str,
        token_url: str,
        get_client_id: Callable[[], Optional[str]],
        get_client_secret: Callable[[], Optional[str]],
        get_redirect_uri: Callable[[], str],
        extract_user_id: Callable[[dict, Optional[str]], str],
        user_info_url: Optional[str] = None,
        extra_token_headers: Optional[dict] = None,
        get_user_access_token: Optional[Callable[[dict], Optional[str]]] = None,
        extract_profile_from_user_info: Optional[Callable[[dict], dict]] = None,
    ):
        self.platform = platform
        self.token_url = token_url
        self.get_client_id = get_client_id
        self.get_client_secret = get_client_secret
        self.get_redirect_uri = get_redirect_uri
        self.extract_user_id = extract_user_id
        self.user_info_url = user_info_url
        self.extra_token_headers = extra_token_headers or {}
        # How to get the access token for user info calls (defaults to top-level access_token)
        self.get_user_access_token = get_user_access_token or (
            lambda data: data.get("access_token")
        )
        # How to extract profile from user info response (defaults to Discord-style)
        self.extract_profile_from_user_info = extract_profile_from_user_info or (
            lambda user_data: {
                "username": user_data.get("username"),
                "display_name": user_data.get("global_name")
                or user_data.get("username"),
            }
        )


PLATFORM_CONFIGS = {
    "discord": PlatformOAuthConfig(
        platform="discord",
        token_url="https://discord.com/api/oauth2/token",  # nosec B106 - OAuth token URL, not a password
        get_client_id=lambda: settings.DISCORD_OAUTH_CLIENT_ID,
        get_client_secret=lambda: settings.DISCORD_OAUTH_CLIENT_SECRET,
        get_redirect_uri=lambda: settings.DISCORD_OAUTH_REDIRECT_URI,
        user_info_url="https://discord.com/api/users/@me",
        extract_user_id=lambda token_data,
        access_token: "",  # uses user_info_url instead
        extra_token_headers={"Content-Type": "application/x-www-form-urlencoded"},
    ),
    "slack": PlatformOAuthConfig(
        platform="slack",
        token_url="https://slack.com/api/oauth.v2.access",  # nosec B106 - OAuth token URL, not a password
        get_client_id=lambda: settings.SLACK_OAUTH_CLIENT_ID,
        get_client_secret=lambda: settings.SLACK_OAUTH_CLIENT_SECRET,
        get_redirect_uri=lambda: settings.SLACK_OAUTH_REDIRECT_URI,
        user_info_url="https://slack.com/api/users.identity",
        extract_user_id=lambda token_data, access_token: token_data["authed_user"][
            "id"
        ],
        # User token lives under authed_user, not at the top level
        get_user_access_token=lambda data: data.get("authed_user", {}).get(
            "access_token"
        ),
        # users.identity returns {"user": {"id": ..., "name": ...}}
        extract_profile_from_user_info=lambda user_data: {
            "username": user_data.get("user", {}).get("name"),
            "display_name": user_data.get("user", {}).get("name"),
        },
    ),
}

router = APIRouter()


def _redirect_url(base: str, path: str, **params: str) -> str:
    """Build a redirect URL, correctly appending query params to a path that may already have them."""
    separator = "&" if "?" in path else "?"
    query = urlencode(params)
    return f"{base}{path}{separator}{query}"


async def _handle_platform_oauth_callback(
    code: Optional[str],
    state: Optional[str],
    error: Optional[str],
    config: PlatformOAuthConfig,
) -> RedirectResponse:
    """Generic OAuth callback handler for all platforms."""
    from app.services.oauth.oauth_state_service import validate_and_consume_oauth_state

    fallback_path = "/settings?section=linked-accounts"

    # Handle OAuth denial
    if error:
        error_type = "cancelled" if error == "access_denied" else "failed"
        return RedirectResponse(
            url=_redirect_url(
                settings.FRONTEND_URL, fallback_path, oauth_error=error_type
            )
        )

    # Validate required params
    if not code or not state:
        return RedirectResponse(
            url=_redirect_url(
                settings.FRONTEND_URL, fallback_path, oauth_error="missing_params"
            )
        )

    # Validate state token
    state_data = await validate_and_consume_oauth_state(state)
    if not state_data:
        return RedirectResponse(
            url=_redirect_url(
                settings.FRONTEND_URL, fallback_path, oauth_error="invalid_state"
            )
        )

    user_id = state_data["user_id"]
    redirect_path = state_data["redirect_path"]

    try:
        # Exchange authorization code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                config.token_url,
                data={
                    "client_id": config.get_client_id(),
                    "client_secret": config.get_client_secret(),
                    "code": code,
                    "redirect_uri": config.get_redirect_uri(),
                    "grant_type": "authorization_code",
                },
                headers=config.extra_token_headers,
            )

            if token_response.status_code != 200:
                logger.error(
                    f"{config.platform} token exchange failed: {token_response.text}"
                )
                return RedirectResponse(
                    url=_redirect_url(
                        settings.FRONTEND_URL, redirect_path, oauth_error="token_failed"
                    )
                )

            token_data = token_response.json()

            # Slack-specific error handling
            if config.platform == "slack" and not token_data.get("ok"):
                logger.error(f"Slack OAuth failed: {token_data.get('error')}")
                return RedirectResponse(
                    url=_redirect_url(
                        settings.FRONTEND_URL, redirect_path, oauth_error="token_failed"
                    )
                )

            access_token = config.get_user_access_token(token_data)

        # Get platform user ID (either from token response or separate API call)
        if config.user_info_url and access_token:
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    config.user_info_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if user_response.status_code != 200:
                    logger.error(
                        f"{config.platform} user fetch failed: {user_response.text}"
                    )
                    return RedirectResponse(
                        url=_redirect_url(
                            settings.FRONTEND_URL,
                            redirect_path,
                            oauth_error="user_fetch_failed",
                        )
                    )

                user_data = user_response.json()
                platform_user_id = (
                    user_data["id"]
                    if "id" in user_data
                    else config.extract_user_id(token_data, access_token)
                )
                profile: dict = config.extract_profile_from_user_info(user_data)
        else:
            platform_user_id = config.extract_user_id(token_data, access_token)
            profile = {}

        # Link platform account to current user (using ObjectId)
        try:
            await PlatformLinkService.link_account(
                user_id, config.platform, platform_user_id, profile=profile or None
            )
            logger.info(
                f"{config.platform} account {platform_user_id} linked to user {user_id} via OAuth"
            )
        except ValueError as e:
            error_msg = str(e)
            if "already linked" in error_msg:
                return RedirectResponse(
                    url=_redirect_url(
                        settings.FRONTEND_URL,
                        redirect_path,
                        oauth_error="already_linked",
                    )
                )
            else:
                logger.error(f"Failed to link account: {error_msg}")
                return RedirectResponse(
                    url=_redirect_url(
                        settings.FRONTEND_URL, redirect_path, oauth_error="failed"
                    )
                )

        # Redirect to settings with success message
        return RedirectResponse(
            url=_redirect_url(
                settings.FRONTEND_URL,
                redirect_path,
                oauth_success="true",
                integration=config.platform,
            )
        )

    except Exception as e:
        logger.error(f"{config.platform} OAuth callback error: {str(e)}", exc_info=True)
        return RedirectResponse(
            url=_redirect_url(
                settings.FRONTEND_URL, redirect_path, oauth_error="failed"
            )
        )


@router.get("/discord/callback")
async def discord_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Discord OAuth callback."""
    return await _handle_platform_oauth_callback(
        code, state, error, PLATFORM_CONFIGS["discord"]
    )


@router.get("/slack/callback")
async def slack_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Slack OAuth callback."""
    return await _handle_platform_oauth_callback(
        code, state, error, PLATFORM_CONFIGS["slack"]
    )
