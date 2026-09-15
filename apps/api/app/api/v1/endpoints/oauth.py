import secrets
from typing import cast
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import RedirectResponse
import httpx
from workos import WorkOSClient

from app.config.settings import settings
from app.constants.auth import (
    DESKTOP_DEEP_LINK,
    MOBILE_DEEP_LINK,
    OAUTH_FLOW_DESKTOP,
    OAUTH_FLOW_MOBILE,
    OAUTH_FLOW_WEB,
    WOS_SESSION_COOKIE,
)
from app.constants.cache import MOBILE_REDIRECT_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.models.oauth_models import MobileLoginUrlResponse, OAuthClientMetadataResponse
from app.services.oauth.composio_callback import (
    ConnectionRejected,
    complete_composio_connection,
    stored_connected_account_id,
)
from app.services.oauth.oauth_service import store_user_info
from app.services.oauth.oauth_state_service import (
    is_safe_redirect_path,
    validate_and_consume_oauth_state,
)
from shared.py.wide_events import OAuthContext, log

router = APIRouter()
http_async_client = httpx.AsyncClient()

workos = WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)


@router.get("/client-metadata.json")
# evlog-map-disable-next-line audit -- public spec-mandated discovery document; no actor, no state change
async def get_client_metadata() -> OAuthClientMetadataResponse:
    """
    OAuth Client ID Metadata Document per draft-ietf-oauth-client-id-metadata-document-00.

    Authorization servers fetch this document when encountering a URL-formatted
    client_id. This enables OAuth flows without pre-registration or DCR.

    The document URL is used as the client_id value.
    See: https://datatracker.ietf.org/doc/html/draft-ietf-oauth-client-id-metadata-document-00
    """
    log.set(oauth=OAuthContext(operation="client_metadata"))
    base_url = get_api_base_url()  # e.g., https://api.heygaia.com
    metadata_url = f"{base_url}/api/v1/oauth/client-metadata.json"

    return OAuthClientMetadataResponse(
        # MUST match this document's URL exactly per spec Section 4.1
        client_id=metadata_url,
        client_name="GAIA",
        client_uri="https://heygaia.com",
        logo_uri=f"{base_url}/static/logo.png",
        redirect_uris=[f"{base_url}/api/v1/mcp/oauth/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )


@router.get("/login/workos", response_class=RedirectResponse)
# evlog-map-disable-next-line audit -- pre-auth redirect; the auth event is audited at the callback
async def login_workos(return_url: str | None = None) -> RedirectResponse:
    """
    Start the WorkOS SSO authentication flow.

    Args:
        return_url: Optional URL to redirect to after authentication.

    Returns:
        RedirectResponse: Redirects the user to the WorkOS SSO authorization URL
    """
    log.set(
        oauth_flow_type=OAUTH_FLOW_WEB,
        oauth=OAuthContext(operation="authorize", provider="authkit"),
    )
    state = secrets.token_urlsafe(32)

    # Store return_url in Redis so we can redirect after callback
    if return_url:
        await redis_cache.client.setex(f"oauth_return_url:{state}", 600, return_url)

    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_REDIRECT_URI,
        state=state,
    )

    return RedirectResponse(url=authorization_url)


async def _store_mobile_redirect(state: str, redirect_uri: str) -> None:
    """Store mobile redirect URI in Redis with TTL."""
    await redis_cache.client.setex(f"mobile_redirect:{state}", MOBILE_REDIRECT_TTL, redirect_uri)


async def _get_and_delete_mobile_redirect(state: str) -> str | None:
    """Get and delete mobile redirect URI from Redis (consume once)."""
    key = f"mobile_redirect:{state}"
    uri = await redis_cache.client.get(key)
    if uri:
        await redis_cache.client.delete(key)
    # RedisCache.client is an untyped property (app/db/redis.py), so .get() resolves
    # to Any; the client is constructed with decode_responses=True, so this is a
    # str (or None) by construction.
    return cast(str | None, uri)


@router.get("/login/workos/mobile")
# evlog-map-disable-next-line audit -- pre-auth redirect; the auth event is audited at the callback
async def login_workos_mobile(redirect_uri: str | None = None) -> MobileLoginUrlResponse:
    """
    Start WorkOS SSO flow for mobile apps (Expo).

    Args:
        redirect_uri: The deep link URI to redirect back to (from Linking.createURL)
    """
    # Generate a unique state to track this auth flow
    state = secrets.token_urlsafe(32)

    # Store the mobile app's redirect URI
    # Default to gaiamobile:// scheme if not provided
    mobile_callback = redirect_uri or MOBILE_DEEP_LINK
    await _store_mobile_redirect(state, mobile_callback)

    log.set(
        oauth_flow_type=OAUTH_FLOW_MOBILE,
        oauth=OAuthContext(operation="authorize", provider="authkit"),
    )
    log.info(
        f"{LogTag.OAUTH} Mobile OAuth started",
        redirect_uri=mobile_callback,
        state_prefix=state[:8],
    )

    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_MOBILE_REDIRECT_URI,
        state=state,
    )
    return MobileLoginUrlResponse(url=authorization_url)


@router.get("/login/google/mobile")
# evlog-map-disable-next-line audit -- pre-auth redirect; the auth event is audited at the callback
async def login_google_mobile(redirect_uri: str | None = None) -> MobileLoginUrlResponse:
    """
    Start Google OAuth flow directly for mobile apps, bypassing the WorkOS hosted UI.
    Users go straight to Google's sign-in page instead of the WorkOS selection screen.

    Args:
        redirect_uri: The deep link URI to redirect back to (from Linking.createURL)
    """
    state = secrets.token_urlsafe(32)
    mobile_callback = redirect_uri or MOBILE_DEEP_LINK
    await _store_mobile_redirect(state, mobile_callback)

    log.set(
        oauth_flow_type=OAUTH_FLOW_MOBILE,
        oauth=OAuthContext(operation="authorize", provider="GoogleOAuth"),
    )
    log.info(
        f"{LogTag.OAUTH} Mobile Google OAuth started",
        redirect_uri=mobile_callback,
        state_prefix=state[:8],
    )

    authorization_url = workos.user_management.get_authorization_url(
        provider="GoogleOAuth",
        redirect_uri=settings.WORKOS_MOBILE_REDIRECT_URI,
        state=state,
    )
    return MobileLoginUrlResponse(url=authorization_url)


@router.get("/workos/mobile/callback", response_class=RedirectResponse)
async def workos_mobile_callback(
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """
    Handle WorkOS SSO callback for mobile (Expo) apps.
    Returns a deep link redirect to the mobile app with the auth token.
    """
    # Get the stored redirect URI for this auth flow
    mobile_redirect: str | None = None
    if state:
        mobile_redirect = await _get_and_delete_mobile_redirect(state)

    if not mobile_redirect:
        mobile_redirect = MOBILE_DEEP_LINK
        log.warning(
            f"{LogTag.OAUTH} No stored redirect URI for state, using default",
            redirect_uri=mobile_redirect,
        )

    log.set(
        oauth_flow_type=OAUTH_FLOW_MOBILE,
        oauth=OAuthContext(operation="callback", provider="authkit"),
    )
    log.info(f"{LogTag.OAUTH} Mobile OAuth callback", redirect_uri=mobile_redirect)

    try:
        if not code:
            log.warning(
                f"{LogTag.OAUTH} No authorization code received from WorkOS (mobile)",
                failure_reason="missing_code",
            )
            return RedirectResponse(url=f"{mobile_redirect}?error=missing_code")

        auth_response = workos.user_management.authenticate_with_code(
            code=code,
            session={
                "seal_session": True,
                "cookie_password": settings.WORKOS_COOKIE_PASSWORD,
            },
        )

        # Extract user information
        email = auth_response.user.email
        first = auth_response.user.first_name or ""
        last = auth_response.user.last_name or ""
        name = f"{first} {last}".strip()
        picture_url = auth_response.user.profile_picture_url

        fields_extracted = [
            field
            for field, value in [
                ("email", email),
                ("name", name),
                ("picture", picture_url),
            ]
            if value
        ]
        log.set(fields_extracted=fields_extracted)

        # Store user info in DB
        user_id, is_new_user = await store_user_info(name, email, picture_url)
        log.set(user_id=str(user_id), is_new_user=is_new_user)
        log.audit(
            "login succeeded",
            actor=str(user_id),
            flow="mobile",
            provider="authkit",
            is_new_user=is_new_user,
        )

        token = auth_response.sealed_session or auth_response.access_token
        return RedirectResponse(url=f"{mobile_redirect}?token={quote(token, safe='')}")

    except HTTPException as e:
        log.error(
            f"{LogTag.OAUTH} HTTP error during WorkOS mobile auth",
            error_type=type(e).__name__,
            error=str(e.detail),
            status_code=e.status_code,
        )
        return RedirectResponse(url=f"{mobile_redirect}?error={e.detail}")

    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Unexpected error during WorkOS mobile callback",
            error_type=type(e).__name__,
            error=str(e),
        )
        return RedirectResponse(url=f"{settings.WORKOS_MOBILE_REDIRECT_URI}?error=server_error")


@router.get("/login/workos/desktop", response_class=RedirectResponse)
# evlog-map-disable-next-line audit -- pre-auth redirect; the auth event is audited at the callback
async def login_workos_desktop() -> RedirectResponse:
    """
    Start the WorkOS SSO authentication flow for desktop app.
    Uses gaia:// protocol for callback redirect.

    Returns:
        RedirectResponse: Redirects the user to the WorkOS SSO authorization URL
    """
    log.set(
        oauth_flow_type=OAUTH_FLOW_DESKTOP,
        oauth=OAuthContext(operation="authorize", provider="authkit"),
    )
    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_DESKTOP_REDIRECT_URI,
    )

    return RedirectResponse(url=authorization_url)


@router.get("/workos/desktop/callback", response_class=RedirectResponse)
async def workos_desktop_callback(
    code: str | None = None,
) -> RedirectResponse:
    """
    Handle the WorkOS SSO callback for desktop app.
    Redirects to gaia:// protocol with auth token.

    Args:
        code: Authorization code from WorkOS

    Returns:
        RedirectResponse to gaia:// deep link with token
    """
    log.set(
        oauth_flow_type=OAUTH_FLOW_DESKTOP,
        oauth=OAuthContext(operation="callback", provider="authkit"),
    )
    try:
        # Validate code parameter
        if not code:
            log.warning(
                f"{LogTag.OAUTH} No authorization code received from WorkOS (desktop)",
                failure_reason="missing_code",
            )
            return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?error=missing_code")

        auth_response = workos.user_management.authenticate_with_code(
            code=code,
            session={
                "seal_session": True,
                "cookie_password": settings.WORKOS_COOKIE_PASSWORD,
            },
        )

        # Extract user information
        email = auth_response.user.email
        first = auth_response.user.first_name or ""
        last = auth_response.user.last_name or ""
        name = f"{first} {last}".strip()
        picture_url = auth_response.user.profile_picture_url

        fields_extracted = [
            field
            for field, value in [
                ("email", email),
                ("name", name),
                ("picture", picture_url),
            ]
            if value
        ]
        log.set(fields_extracted=fields_extracted)

        # Store user info in our database
        user_id, is_new_user = await store_user_info(name, email, picture_url)
        log.set(user_id=str(user_id), is_new_user=is_new_user)
        log.audit(
            "login succeeded",
            actor=str(user_id),
            flow="desktop",
            provider="authkit",
            is_new_user=is_new_user,
        )

        # Return token via deep link - desktop app will handle storage
        token = auth_response.sealed_session or auth_response.access_token
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?token={quote(token, safe='')}")

    except HTTPException as e:
        log.error(
            f"{LogTag.OAUTH} HTTP error during WorkOS desktop auth",
            error_type=type(e).__name__,
            error=str(e.detail),
            status_code=e.status_code,
        )
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?error={e.detail}")

    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Unexpected error during WorkOS desktop callback",
            error_type=type(e).__name__,
            error=str(e),
        )
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?error=server_error")


@router.get("/workos/callback", response_class=RedirectResponse)
async def workos_callback(
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """
    Handle the WorkOS SSO callback.

    Args:
        code: Authorization code from WorkOS
        state: State token carrying return_url reference

    Returns:
        RedirectResponse to the frontend with auth tokens
    """
    # Retrieve and consume return_url from Redis
    return_url: str | None = None
    if state:
        key = f"oauth_return_url:{state}"
        return_url = await redis_cache.client.get(key)
        if return_url:
            await redis_cache.client.delete(key)

    log.set(
        oauth_flow_type=OAUTH_FLOW_WEB,
        oauth=OAuthContext(operation="callback", provider="authkit"),
    )
    try:
        # Validate code parameter
        if not code:
            log.warning(
                f"{LogTag.OAUTH} No authorization code received from WorkOS",
                failure_reason="missing_code",
            )
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=missing_code")

        auth_response = workos.user_management.authenticate_with_code(
            code=code,
            session={
                "seal_session": True,
                "cookie_password": settings.WORKOS_COOKIE_PASSWORD,
            },
        )

        # Extract user information
        email = auth_response.user.email
        first = auth_response.user.first_name or ""
        last = auth_response.user.last_name or ""
        name = f"{first} {last}".strip()
        picture_url = auth_response.user.profile_picture_url

        fields_extracted = [
            field
            for field, value in [
                ("email", email),
                ("name", name),
                ("picture", picture_url),
            ]
            if value
        ]
        log.set(fields_extracted=fields_extracted)

        # Store user info in our database
        user_id, is_new_user = await store_user_info(name, email, picture_url)
        log.set(user_id=str(user_id), is_new_user=is_new_user)
        log.audit(
            "login succeeded",
            actor=str(user_id),
            flow="web",
            provider="authkit",
            is_new_user=is_new_user,
        )

        # Redirect to return_url if provided and safe, otherwise default /redirect
        if return_url and is_safe_redirect_path(return_url):
            destination = f"{settings.FRONTEND_URL}{return_url}"
        else:
            destination = f"{settings.FRONTEND_URL}/redirect"

        response = RedirectResponse(url=destination)

        # Set cookies with appropriate security settings
        response.set_cookie(
            key=WOS_SESSION_COOKIE,
            value=auth_response.sealed_session or auth_response.access_token,
            httponly=True,
            secure=settings.ENV == "production",
            samesite="lax",
        )

        return response

    except HTTPException as e:
        log.error(
            f"{LogTag.OAUTH} HTTP error during WorkOS",
            error_type=type(e).__name__,
            error=str(e.detail),
            status_code=e.status_code,
        )
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error={e.detail}")

    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Unexpected error during WorkOS callback",
            error_type=type(e).__name__,
            error=str(e),
        )
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=server_error")


def _composio_failure(redirect_path: str, error: str) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error={error}")


@router.get("/composio/callback", response_class=RedirectResponse)
async def composio_callback(
    status: str,
    state: str,
    background_tasks: BackgroundTasks,
    connectedAccountId: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """
    Handle Composio OAuth callback after successful/failed connection.

    Args:
        status: Connection status from Composio ('success' or 'failed')
        state: Secure state token for CSRF protection and redirect path
        background_tasks: FastAPI background tasks for async operations
        connectedAccountId: Unique identifier for the connected account (optional for failures)
        error: Error code from OAuth provider (optional)

    Returns:
        RedirectResponse: Redirects user to frontend with appropriate status
    """
    log.set(operation="composio_callback", oauth={"provider": "composio", "status": status})
    # Validate and consume state token
    state_data = await validate_and_consume_oauth_state(state)
    if not state_data:
        log.warning(f"{LogTag.OAUTH} Invalid OAuth state token", state_prefix=state[:8])
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/redirect?oauth_error=invalid_state")

    redirect_path = state_data["redirect_path"]

    # Handle failed connection early
    if status != "success":
        error_type = "cancelled" if error == "access_denied" else "failed"
        log.warning(
            f"{LogTag.OAUTH} Composio connection failed",
            status=status,
            error=error,
            connected_account_id=connectedAccountId,
        )
        return _composio_failure(redirect_path, error_type)

    connected_account_id = connectedAccountId or await stored_connected_account_id(state_data)
    if not connected_account_id:
        log.error(
            f"{LogTag.OAUTH} Connected account ID missing for successful connection",
            failure_reason="missing_connected_account_id",
            status=status,
        )
        return _composio_failure(redirect_path, "failed")

    try:
        outcome = await complete_composio_connection(
            connected_account_id,
            expected_user_id=state_data["user_id"],
            background_tasks=background_tasks,
        )
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Unexpected error in Composio callback",
            connected_account_id=connected_account_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed")
    if isinstance(outcome, ConnectionRejected):
        if outcome.reason in ("account_not_found", "user_missing"):
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed")
        return _composio_failure(
            redirect_path, "failed" if outcome.reason == "config_missing" else outcome.reason
        )
    log.audit(
        "integration connected",
        actor=outcome.user_id,
        resource=outcome.integration_id,
        provider=outcome.provider,
    )
    separator = "?" if "?" not in redirect_path else "&"
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}{redirect_path}{separator}"
        f"oauth_success=true&integration={outcome.integration_id}"
    )
