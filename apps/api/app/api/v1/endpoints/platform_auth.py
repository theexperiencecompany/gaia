from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
import httpx

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.outbound_delivery import notify_account_linked
from app.services.platform_link_service import PlatformLinkService
from shared.py.wide_events import log


class PlatformOAuthConfig:
    """Configuration for platform-specific OAuth flows.

    The provider payloads (``token_data``, ``user_data``) stay ``dict[str, Any]``
    on purpose: they are Discord's and Slack's response bodies, and the accessors
    below read only the two or three keys each flow needs. Modelling the rest
    would be inventing a third-party schema from the fields we happen to touch.
    """

    def __init__(
        self,
        *,
        platform: str,
        token_url: str,
        get_client_id: Callable[[], str | None],
        get_client_secret: Callable[[], str | None],
        get_redirect_uri: Callable[[], str],
        extract_user_id: Callable[[dict[str, Any], str | None], str],
        user_info_url: str | None = None,
        extra_token_headers: dict[str, str] | None = None,
        get_user_access_token: Callable[[dict[str, Any]], str | None] | None = None,
        extract_profile_from_user_info: Callable[[dict[str, Any]], dict[str, str | None]]
        | None = None,
    ) -> None:
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
                "display_name": user_data.get("global_name") or user_data.get("username"),
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
        extract_user_id=lambda token_data, access_token: "",  # uses user_info_url instead
        extra_token_headers={"Content-Type": "application/x-www-form-urlencoded"},
    ),
    "slack": PlatformOAuthConfig(
        platform="slack",
        token_url="https://slack.com/api/oauth.v2.access",  # nosec B106 - OAuth token URL, not a password
        get_client_id=lambda: settings.SLACK_OAUTH_CLIENT_ID,
        get_client_secret=lambda: settings.SLACK_OAUTH_CLIENT_SECRET,
        get_redirect_uri=lambda: settings.SLACK_OAUTH_REDIRECT_URI,
        user_info_url="https://slack.com/api/users.identity",
        extract_user_id=lambda token_data, access_token: token_data["authed_user"]["id"],
        # User token lives under authed_user, not at the top level
        get_user_access_token=lambda data: data.get("authed_user", {}).get("access_token"),
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
    code: str | None,
    state: str | None,
    error: str | None,
    config: PlatformOAuthConfig,
) -> RedirectResponse:
    """Generic OAuth callback handler for all platforms."""
    from app.services.oauth.oauth_state_service import validate_and_consume_oauth_state

    fallback_path = "/settings?section=linked-accounts"

    # Handle OAuth denial
    if error:
        error_type = "cancelled" if error == "access_denied" else "failed"
        return RedirectResponse(
            url=_redirect_url(settings.FRONTEND_URL, fallback_path, oauth_error=error_type)
        )

    # Validate required params
    if not code or not state:
        return RedirectResponse(
            url=_redirect_url(settings.FRONTEND_URL, fallback_path, oauth_error="missing_params")
        )

    # Validate state token
    state_data = await validate_and_consume_oauth_state(state)
    if not state_data:
        return RedirectResponse(
            url=_redirect_url(settings.FRONTEND_URL, fallback_path, oauth_error="invalid_state")
        )

    user_id = state_data["user_id"]
    redirect_path = state_data["redirect_path"]
    log.set(
        user={"id": user_id},
        platform=config.platform,
        operation="platform_oauth_callback",
    )

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
                log.error(
                    f"{LogTag.API} Platform token exchange failed",
                    platform=config.platform,
                    status_code=token_response.status_code,
                    error=token_response.text,
                )
                return RedirectResponse(
                    url=_redirect_url(
                        settings.FRONTEND_URL, redirect_path, oauth_error="token_failed"
                    )
                )

            token_data = token_response.json()

            # Slack-specific error handling
            if config.platform == "slack" and not token_data.get("ok"):
                log.error(f"{LogTag.API} Slack OAuth failed", error=token_data.get("error"))
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
                    log.error(
                        f"{LogTag.API} Platform user fetch failed",
                        platform=config.platform,
                        status_code=user_response.status_code,
                        error=user_response.text,
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
                profile: dict[str, str | None] = config.extract_profile_from_user_info(user_data)
        else:
            platform_user_id = config.extract_user_id(token_data, access_token)
            profile = {}

        log.set(profile_fields_extracted=list(profile.keys()))

        # Link platform account to current user (using ObjectId)
        try:
            link_result = await PlatformLinkService.link_account(
                user_id, config.platform, platform_user_id, profile=profile or None
            )
            # Audited immediately after the link lands, before the notification —
            # a failing notification must not erase the record of the state change.
            log.audit(
                "platform account linked",
                actor=user_id,
                resource=platform_user_id,
                provider=config.platform,
                is_new_link=bool(link_result.is_new_link),
            )
            # capture_event, not capture_context_event: this is a third-party
            # OAuth redirect, so the request carries no WorkOS session for the
            # PostHog context middleware to identify. The user id comes from the
            # signed state token — pass it explicitly or the event lands on an
            # anonymous profile.
            capture_event(
                user_id,
                AnalyticsEvents.INTEGRATION_CONNECTED,
                {
                    "integration_id": config.platform,
                    "is_new_link": bool(link_result.is_new_link),
                },
            )
            if link_result.is_new_link:
                await notify_account_linked(config.platform, user_id)
        except ValueError as e:
            error_msg = str(e)
            if "already linked" in error_msg:
                log.set(outcome="already_linked")
                log.audit(
                    "platform account link rejected",
                    actor=user_id,
                    resource=platform_user_id,
                    provider=config.platform,
                    reason="already_linked",
                )
                return RedirectResponse(
                    url=_redirect_url(
                        settings.FRONTEND_URL,
                        redirect_path,
                        oauth_error="already_linked",
                    )
                )
            log.error(
                f"{LogTag.API} Failed to link account",
                platform=config.platform,
                user_id=user_id,
                error_type=type(e).__name__,
                error=error_msg,
            )
            log.audit(
                "platform account link failed",
                actor=user_id,
                resource=platform_user_id,
                provider=config.platform,
                error_type=type(e).__name__,
            )
            return RedirectResponse(
                url=_redirect_url(settings.FRONTEND_URL, redirect_path, oauth_error="failed")
            )

        # Redirect to settings with success message
        log.set(outcome="success")
        return RedirectResponse(
            url=_redirect_url(
                settings.FRONTEND_URL,
                redirect_path,
                oauth_success="true",
                integration=config.platform,
            )
        )

    except Exception as e:
        log.set(outcome="failed")
        log.error(
            f"{LogTag.API} Platform OAuth callback error",
            platform=config.platform,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        return RedirectResponse(
            url=_redirect_url(settings.FRONTEND_URL, redirect_path, oauth_error="failed")
        )


@router.get("/discord/callback")
# evlog-map-disable-next-line audit -- audited at the state change in _handle_platform_oauth_callback
async def discord_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Discord OAuth callback."""
    log.set(oauth={"operation": "callback", "provider": "discord", "error_type": error})
    return await _handle_platform_oauth_callback(code, state, error, PLATFORM_CONFIGS["discord"])


@router.get("/slack/callback")
# evlog-map-disable-next-line audit -- audited at the state change in _handle_platform_oauth_callback
async def slack_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Slack OAuth callback."""
    log.set(oauth={"operation": "callback", "provider": "slack", "error_type": error})
    return await _handle_platform_oauth_callback(code, state, error, PLATFORM_CONFIGS["slack"])
