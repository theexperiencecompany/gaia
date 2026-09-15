from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
import httpx

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.services.platform_link_completion import complete_platform_link
from app.utils.errors import AppError
from shared.py.wide_events import log


def _top_level_access_token(token_data: dict[str, Any]) -> str | None:
    token = token_data.get("access_token")
    return token if isinstance(token, str) else None


def _discord_style_profile(user_data: dict[str, Any]) -> dict[str, str | None]:
    return {
        "username": user_data.get("username"),
        "display_name": user_data.get("global_name") or user_data.get("username"),
    }


@dataclass(kw_only=True, frozen=True)
class PlatformOAuthConfig:
    """Configuration for platform-specific OAuth flows.

    The provider payloads (``token_data``, ``user_data``) stay ``dict[str, Any]``
    on purpose: they are Discord's and Slack's response bodies, and the accessors
    below read only the two or three keys each flow needs. Modelling the rest
    would be inventing a third-party schema from the fields we happen to touch.
    """

    platform: str
    token_url: str
    get_client_id: Callable[[], str | None]
    get_client_secret: Callable[[], str | None]
    get_redirect_uri: Callable[[], str]
    extract_user_id: Callable[[dict[str, Any], str | None], str]
    user_info_url: str | None = None
    extra_token_headers: dict[str, str] = field(default_factory=dict)
    # Where the user-level access token sits in the token response.
    get_user_access_token: Callable[[dict[str, Any]], str | None] = _top_level_access_token
    # How the user-info response maps to a profile.
    extract_profile_from_user_info: Callable[[dict[str, Any]], dict[str, str | None]] = (
        _discord_style_profile
    )


PLATFORM_CONFIGS = {
    "discord": PlatformOAuthConfig(
        platform="discord",
        token_url="https://discord.com/api/oauth2/token",  # nosec B106 - OAuth token URL, not a password
        get_client_id=lambda: settings.DISCORD_OAUTH_CLIENT_ID,
        get_client_secret=lambda: settings.DISCORD_OAUTH_CLIENT_SECRET,
        get_redirect_uri=lambda: settings.DISCORD_OAUTH_REDIRECT_URI,
        user_info_url="https://discord.com/api/users/@me",
        extract_user_id=lambda _token_data, _access_token: "",  # uses user_info_url instead
        extra_token_headers={"Content-Type": "application/x-www-form-urlencoded"},
    ),
    "slack": PlatformOAuthConfig(
        platform="slack",
        token_url="https://slack.com/api/oauth.v2.access",  # nosec B106 - OAuth token URL, not a password
        get_client_id=lambda: settings.SLACK_OAUTH_CLIENT_ID,
        get_client_secret=lambda: settings.SLACK_OAUTH_CLIENT_SECRET,
        get_redirect_uri=lambda: settings.SLACK_OAUTH_REDIRECT_URI,
        user_info_url="https://slack.com/api/users.identity",
        extract_user_id=lambda token_data, _access_token: token_data["authed_user"]["id"],
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


FALLBACK_PATH = "/settings?section=linked-accounts"


def _bounce(path: str, **params: str) -> RedirectResponse:
    return RedirectResponse(url=_redirect_url(settings.FRONTEND_URL, path, **params))


class _CallbackRefused(Exception):
    """A step of the callback turned the user away; ``oauth_error`` names why."""

    def __init__(self, oauth_error: str) -> None:
        super().__init__(oauth_error)
        self.oauth_error = oauth_error


async def _exchange_code(config: PlatformOAuthConfig, code: str) -> dict[str, Any]:
    """The provider's token response for ``code``."""
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
        raise _CallbackRefused("token_failed")
    token_data: dict[str, Any] = token_response.json()
    # Slack answers 200 with ok=false on a bad exchange.
    if config.platform == "slack" and not token_data.get("ok"):
        log.error(f"{LogTag.API} Slack OAuth failed", error=token_data.get("error"))
        raise _CallbackRefused("token_failed")
    return token_data


async def _resolve_platform_user(
    config: PlatformOAuthConfig, token_data: dict[str, Any]
) -> tuple[str, dict[str, str | None]]:
    """The platform user id and profile, from the token response or the user-info call."""
    access_token = config.get_user_access_token(token_data)
    if not (config.user_info_url and access_token):
        return config.extract_user_id(token_data, access_token), {}

    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            config.user_info_url, headers={"Authorization": f"Bearer {access_token}"}
        )
    if user_response.status_code != 200:
        log.error(
            f"{LogTag.API} Platform user fetch failed",
            platform=config.platform,
            status_code=user_response.status_code,
            error=user_response.text,
        )
        raise _CallbackRefused("user_fetch_failed")
    user_data = user_response.json()
    platform_user_id = (
        user_data["id"] if "id" in user_data else config.extract_user_id(token_data, access_token)
    )
    return platform_user_id, config.extract_profile_from_user_info(user_data)


async def _link_platform_account(
    user_id: str, config: PlatformOAuthConfig, platform_user_id: str, profile: dict[str, str | None]
) -> None:
    try:
        completion = await complete_platform_link(
            user_id, config.platform, platform_user_id, profile=profile or None
        )
    except AppError as e:
        if e.status_code == 409:
            # complete_platform_link already audited the rejection.
            log.set(outcome="already_linked")
            raise _CallbackRefused("already_linked") from e
        log.error(
            f"{LogTag.API} Failed to link account",
            platform=config.platform,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        log.audit(
            "platform account link failed",
            actor=user_id,
            resource=platform_user_id,
            provider=config.platform,
            error_type=type(e).__name__,
        )
        raise _CallbackRefused("failed") from e
    log.audit(
        "platform account linked",
        actor=user_id,
        resource=platform_user_id,
        provider=config.platform,
        is_new_link=completion.link.is_new_link,
    )


async def _handle_platform_oauth_callback(
    code: str | None,
    state: str | None,
    error: str | None,
    config: PlatformOAuthConfig,
) -> RedirectResponse:
    """Generic OAuth callback handler for all platforms."""
    # Deferred import: deferred import kept out of module load path
    from app.services.oauth import oauth_state_service  # noqa: PLC0415 -- deferred

    if error:
        return _bounce(
            FALLBACK_PATH, oauth_error="cancelled" if error == "access_denied" else "failed"
        )
    if not code or not state:
        return _bounce(FALLBACK_PATH, oauth_error="missing_params")
    state_data = await oauth_state_service.validate_and_consume_oauth_state(state)
    if not state_data:
        return _bounce(FALLBACK_PATH, oauth_error="invalid_state")

    user_id = state_data["user_id"]
    redirect_path = state_data["redirect_path"]
    log.set(
        user={"id": user_id},
        platform=config.platform,
        operation="platform_oauth_callback",
    )
    try:
        token_data = await _exchange_code(config, code)
        platform_user_id, profile = await _resolve_platform_user(config, token_data)
        log.set(profile_fields_extracted=list(profile.keys()))
        await _link_platform_account(user_id, config, platform_user_id, profile)
    except _CallbackRefused as refused:
        return _bounce(redirect_path, oauth_error=refused.oauth_error)
    except Exception as e:
        log.set(outcome="failed")
        log.error(
            f"{LogTag.API} Platform OAuth callback error",
            platform=config.platform,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        return _bounce(redirect_path, oauth_error="failed")

    log.set(outcome="success")
    return _bounce(redirect_path, oauth_success="true", integration=config.platform)


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
