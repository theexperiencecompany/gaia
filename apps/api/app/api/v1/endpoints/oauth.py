from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from workos import WorkOSClient

from app.config.loggers import auth_logger as logger
from app.config.oauth_config import get_integration_by_config
from app.config.settings import settings
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.services.calendar_service import initialize_calendar_preferences
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.integration_service import update_user_integration_status
from app.services.oauth.oauth_service import handle_oauth_connection, store_user_info
from app.services.oauth.oauth_state_service import validate_and_consume_oauth_state
from app.utils.oauth_utils import fetch_user_info_from_google, get_tokens_from_code

router = APIRouter()
http_async_client = httpx.AsyncClient()

workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


@router.get("/client-metadata.json")
async def get_client_metadata():
    """
    OAuth Client ID Metadata Document per draft-ietf-oauth-client-id-metadata-document-00.

    Authorization servers fetch this document when encountering a URL-formatted
    client_id. This enables OAuth flows without pre-registration or DCR.

    The document URL is used as the client_id value.
    See: https://datatracker.ietf.org/doc/html/draft-ietf-oauth-client-id-metadata-document-00
    """
    base_url = get_api_base_url()  # e.g., https://api.heygaia.com
    metadata_url = f"{base_url}/api/v1/oauth/client-metadata.json"

    return JSONResponse(
        content={
            # MUST match this document's URL exactly per spec Section 4.1
            "client_id": metadata_url,
            "client_name": "GAIA AI Assistant",
            "client_uri": "https://heygaia.com",
            "logo_uri": f"{base_url}/static/logo.png",
            "redirect_uris": [f"{base_url}/api/v1/mcp/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            # MUST be "none" - no client secrets allowed per spec Section 4.1
            "token_endpoint_auth_method": "none",
        },
        media_type="application/json",
    )


@router.get("/login/workos")
async def login_workos():
    """
    Start the WorkOS SSO authentication flow.

    Returns:
        RedirectResponse: Redirects the user to the WorkOS SSO authorization URL
    """
    # Add any needed parameters for your SSO implementation
    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_REDIRECT_URI,
    )

    return RedirectResponse(url=authorization_url)


@router.get("/login/workos/mobile")
async def login_workos_mobile():
    """Start WorkOS SSO flow for mobile apps (Expo)."""
    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_MOBILE_REDIRECT_URI,
    )
    return {"url": authorization_url}


@router.get("/workos/mobile/callback")
async def workos_mobile_callback(code: Optional[str] = None) -> RedirectResponse:
    """
    Handle WorkOS SSO callback for mobile (Expo) apps.
    Returns a deep link redirect to the mobile app with the auth token.
    """
    try:
        if not code:
            logger.error("No authorization code received from WorkOS (mobile)")
            return RedirectResponse(
                url=f"{settings.WORKOS_MOBILE_REDIRECT_URI}?error=missing_code"
            )

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

        # Store user info in DB
        await store_user_info(name, email, picture_url)

        token = auth_response.sealed_session or auth_response.access_token
        return RedirectResponse(url=f"gaiamobile://auth/callback?token={token}")

    except HTTPException as e:
        logger.error(f"HTTP error during WorkOS mobile auth: {e.detail}")
        return RedirectResponse(
            url=f"{settings.WORKOS_MOBILE_REDIRECT_URI}?error={e.detail}"
        )

    except Exception as e:
        logger.error(f"Unexpected error during WorkOS mobile callback: {str(e)}")
        return RedirectResponse(
            url=f"{settings.WORKOS_MOBILE_REDIRECT_URI}?error=server_error"
        )


@router.get("/login/workos/desktop")
async def login_workos_desktop():
    """
    Start the WorkOS SSO authentication flow for desktop app.
    Uses gaia:// protocol for callback redirect.

    Returns:
        RedirectResponse: Redirects the user to the WorkOS SSO authorization URL
    """
    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_DESKTOP_REDIRECT_URI,
    )

    return RedirectResponse(url=authorization_url)


@router.get("/workos/desktop/callback")
async def workos_desktop_callback(
    code: Optional[str] = None,
) -> RedirectResponse:
    """
    Handle the WorkOS SSO callback for desktop app.
    Redirects to gaia:// protocol with auth token.

    Args:
        code: Authorization code from WorkOS

    Returns:
        RedirectResponse to gaia:// deep link with token
    """
    try:
        # Validate code parameter
        if not code:
            logger.error("No authorization code received from WorkOS (desktop)")
            return RedirectResponse(url="gaia://auth/callback?error=missing_code")

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

        # Store user info in our database
        await store_user_info(name, email, picture_url)

        # Return token via deep link - desktop app will handle storage
        token = auth_response.sealed_session or auth_response.access_token
        return RedirectResponse(url=f"gaia://auth/callback?token={token}")

    except HTTPException as e:
        logger.error(f"HTTP error during WorkOS desktop auth: {e.detail}")
        return RedirectResponse(url=f"gaia://auth/callback?error={e.detail}")

    except Exception as e:
        logger.error(f"Unexpected error during WorkOS desktop callback: {str(e)}")
        return RedirectResponse(url="gaia://auth/callback?error=server_error")


@router.get("/workos/callback")
async def workos_callback(
    code: Optional[str] = None,
) -> RedirectResponse:
    """
    Handle the WorkOS SSO callback.

    Args:
        code: Authorization code from WorkOS

    Returns:
        RedirectResponse to the frontend with auth tokens
    """
    try:
        # Validate code parameter
        if not code:
            logger.error("No authorization code received from WorkOS")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/login?error=missing_code"
            )

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

        # Store user info in our database
        await store_user_info(name, email, picture_url)

        # Set cookies and redirect to frontend
        redirect_url = settings.FRONTEND_URL
        response = RedirectResponse(url=f"{redirect_url}/redirect")

        # Set cookies with appropriate security settings
        response.set_cookie(
            key="wos_session",
            value=auth_response.sealed_session or auth_response.access_token,
            httponly=True,
            secure=settings.ENV == "production",
            samesite="lax",
        )

        return response

    except HTTPException as e:
        logger.error(f"HTTP error during WorkOS : {e.detail}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error={e.detail}")

    except Exception as e:
        logger.error(f"Unexpected error during WorkOS callback: {str(e)}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=server_error")


@router.get("/composio/callback", response_class=RedirectResponse)
async def composio_callback(
    status: str,
    state: str,
    background_tasks: BackgroundTasks,
    connectedAccountId: Optional[str] = None,
    error: Optional[str] = None,
):
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
    # Validate and consume state token
    state_data = await validate_and_consume_oauth_state(state)
    if not state_data:
        logger.error(f"Invalid OAuth state token: {state}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/redirect?oauth_error=invalid_state"
        )

    redirect_path = state_data["redirect_path"]
    expected_user_id = state_data["user_id"]

    # Handle failed connection early
    if status != "success":
        error_type = "cancelled" if error == "access_denied" else "failed"
        logger.warning(
            f"Composio connection failed: status={status}, error={error}, accountId={connectedAccountId}"
        )
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error={error_type}"
        )

    # Ensure we have connectedAccountId for success status
    if not connectedAccountId:
        logger.error("Connected account ID missing for successful connection")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=failed"
        )

    composio_service = get_composio_service()
    try:
        # Retrieve connected account details
        connected_account = composio_service.get_connected_account_by_id(
            connectedAccountId
        )

        if not connected_account:
            logger.error(f"Connected account not found: {connectedAccountId}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
            )

        # Extract essential information
        config_id = connected_account.auth_config.id
        user_id = connected_account.user_id  # type: ignore

        if not user_id:
            logger.error(f"User ID missing for account: {connectedAccountId}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
            )

        # Find integration configuration by auth config ID
        integration_config = get_integration_by_config(config_id)
        if not integration_config:
            logger.error(
                f"Integration config not found for auth_config_id: {config_id}"
            )
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=failed"
            )

        # Verify user_id matches the state token (security check)
        if str(user_id) != expected_user_id:
            logger.error(
                f"User ID mismatch: state={expected_user_id}, account={user_id}"
            )
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=user_mismatch"
            )

        await handle_oauth_connection(
            user_id=str(user_id),
            integration_config=integration_config,
            connected_account_id=connectedAccountId,
            background_tasks=background_tasks,
        )

        # Successful connection - redirect to frontend with success indicator
        logger.info(
            f"Composio connection successful: user={user_id}, "
            f"integration={integration_config.id}, account={connectedAccountId}"
        )
        # Add success parameter and integration name to URL
        separator = "?" if "?" not in redirect_path else "&"
        redirect_url = f"{settings.FRONTEND_URL}/{redirect_path}{separator}oauth_success=true&integration={integration_config.id}"
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.error(
            f"Unexpected error in Composio callback: {str(e)}, "
            f"accountId={connectedAccountId}",
            exc_info=True,
        )
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
        )


@router.get("/google/callback", response_class=RedirectResponse)
async def callback(
    background_tasks: BackgroundTasks,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    try:
        # Validate and consume state token first
        state_data = None
        redirect_path = "/redirect"  # Default fallback

        if state:
            state_data = await validate_and_consume_oauth_state(state)
            if not state_data:
                logger.error(f"Invalid OAuth state token: {state}")
                return RedirectResponse(
                    url=f"{settings.FRONTEND_URL}/redirect?oauth_error=invalid_state"
                )
            redirect_path = state_data["redirect_path"]
        else:
            # For backward compatibility with old flows without state
            logger.warning("OAuth callback received without state token")

        # Handle OAuth errors (e.g., user canceled)
        if error:
            logger.warning(f"OAuth error: {error}")
            if error == "access_denied":
                # User canceled OAuth flow
                redirect_url = (
                    f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=cancelled"
                )
            else:
                # Other OAuth errors
                redirect_url = (
                    f"{settings.FRONTEND_URL}{redirect_path}?oauth_error={error}"
                )
            return RedirectResponse(url=redirect_url)

        # Check if we have the authorization code
        if not code:
            logger.error("No authorization code provided")
            redirect_url = f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=no_code"
            return RedirectResponse(url=redirect_url)

        # Get tokens from authorization code
        tokens = await get_tokens_from_code(code)
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        if not access_token and not refresh_token:
            raise HTTPException(
                status_code=400, detail="Missing access or refresh token"
            )

        # Get user info using access token
        user_info = await fetch_user_info_from_google(access_token)
        user_email = user_info.get("email")
        user_name = user_info.get("name")
        user_picture = user_info.get("picture")

        if not user_email:
            raise HTTPException(status_code=400, detail="Email not found in user info")

        # Store user info and get user_id
        user_id = await store_user_info(user_name, user_email, user_picture)

        # Verify user_id matches the state token if we have one (security check)
        if state_data and str(user_id) != state_data["user_id"]:
            logger.error(
                f"User ID mismatch: state={state_data['user_id']}, token={user_id}"
            )
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=user_mismatch"
            )

        # Store token in the repository
        await token_repository.store_token(
            user_id=str(user_id),
            provider="google",
            token_data={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": tokens.get("token_type", "Bearer"),
                "expires_in": tokens.get("expires_in", 3600),  # Default 1 hour,
                "scope": tokens.get("scope", ""),
            },
        )

        # Invalidate OAuth status cache for this user
        try:
            cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
            await delete_cache(cache_key)
            logger.info(f"OAuth status cache invalidated for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate OAuth status cache: {e}")

        # Initialize calendar preferences (select all calendars by default)
        await initialize_calendar_preferences(
            user_id=str(user_id),
            access_token=access_token,
        )

        # Update user_integrations for connected Google integrations
        try:
            scope = tokens.get("scope", "")
            if "gmail" in scope.lower() or "mail" in scope.lower():
                await update_user_integration_status(str(user_id), "gmail", "connected")
                logger.info("Updated user_integrations for gmail")
            if "calendar" in scope.lower():
                await update_user_integration_status(
                    str(user_id), "google_calendar", "connected"
                )
                logger.info("Updated user_integrations for google_calendar")
        except Exception as e:
            logger.warning(f"Failed to update user_integrations for Google scopes: {e}")

        # Redirect to the original page with success indicator
        separator = "&" if "?" in redirect_path else "?"
        redirect_url = f"{settings.FRONTEND_URL}{redirect_path}{separator}oauth_success=true&integration=google"
        response = RedirectResponse(url=redirect_url)

        return response

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
