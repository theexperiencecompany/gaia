import base64
import hashlib
import hmac
import secrets
from typing import Optional

import httpx
from shared.py.wide_events import log
from app.config.oauth_config import get_integration_by_config
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
from app.db.redis import redis_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.services.composio.composio_service import get_composio_service
from app.services.oauth.oauth_service import handle_oauth_connection, store_user_info
from app.services.oauth.oauth_state_service import validate_and_consume_oauth_state
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from workos import WorkOSClient

router = APIRouter()
http_async_client = httpx.AsyncClient()

# One-time OAuth code exchange. We no longer put the sealed session token in
# the deep-link query string (it ends up in logs / breadcrumbs / Referer
# headers). Instead, after a successful WorkOS callback we:
#   1. Generate a short opaque ``code`` value.
#   2. Store ``code -> sealed_session`` in Redis with a 5-minute TTL.
#   3. Redirect to ``deep_link?code=<code>``.
#   4. The client POSTs the code to ``/oauth/exchange-code`` over TLS and
#      gets the sealed session in the response body.
_OAUTH_CODE_EXCHANGE_PREFIX = "oauth_code_exchange"
_OAUTH_CODE_EXCHANGE_TTL = 300  # 5 minutes
# CSRF binding for the desktop/mobile auth flow.
_OAUTH_STATE_PREFIX = "oauth_state_binding"
_OAUTH_STATE_TTL = 600  # 10 minutes


async def _store_oauth_exchange_code(
    token: str, code_challenge: Optional[str] = None
) -> str:
    """Store a sealed session in Redis and return a short opaque code.

    If ``code_challenge`` is set (H11 PKCE), it is stored alongside the
    token so /oauth/exchange-code can verify the client's ``code_verifier``.
    """
    code = secrets.token_urlsafe(32)
    # Pack as ``<token>|<challenge>`` so a single GET yields both halves.
    packed = f"{token}|{code_challenge}" if code_challenge else token
    await redis_cache.client.setex(
        f"{_OAUTH_CODE_EXCHANGE_PREFIX}:{code}", _OAUTH_CODE_EXCHANGE_TTL, packed
    )
    return code


async def _consume_oauth_exchange_code(
    code: str, code_verifier: Optional[str] = None
) -> Optional[str]:
    """Atomically consume an exchange code and return the stored token.

    When the code was stored with a PKCE challenge, ``code_verifier`` must
    hash to that challenge or the exchange is rejected.
    """
    key = f"{_OAUTH_CODE_EXCHANGE_PREFIX}:{code}"
    packed = await redis_cache.client.get(key)
    if not packed:
        return None
    # One-time use — delete after read.
    await redis_cache.client.delete(key)
    token, _, stored_challenge = packed.partition("|")
    if stored_challenge:
        if not code_verifier:
            return None
        computed = _sha256_b64url(code_verifier)
        if not hmac.compare_digest(computed, stored_challenge):
            return None
    return token


async def _store_oauth_state(
    state: str, flow: str, code_challenge: Optional[str] = None
) -> None:
    """Bind a CSRF state to the flow that produced it.

    When ``code_challenge`` is provided (H11 PKCE), it is stored alongside
    the flow and retrieved at exchange-code time so we can verify the
    client presents a matching ``code_verifier``.
    """
    payload = flow
    if code_challenge:
        payload = f"{flow}|{code_challenge}"
    await redis_cache.client.setex(
        f"{_OAUTH_STATE_PREFIX}:{state}", _OAUTH_STATE_TTL, payload
    )


async def _consume_oauth_state(state: str, expected_flow: str) -> bool:
    """Validate + consume the state; returns True iff it matches the flow.

    Also side-effects the stored code_challenge onto the exchange-code
    entry so /oauth/exchange-code can enforce PKCE.
    """
    if not state:
        return False
    key = f"{_OAUTH_STATE_PREFIX}:{state}"
    stored = await redis_cache.client.get(key)
    if not stored:
        return False
    await redis_cache.client.delete(key)
    flow_part, _, challenge_part = stored.partition("|")
    if flow_part != expected_flow:
        return False
    # Tuck the challenge into a side channel that the callback picks up
    # before minting the exchange code. Keyed by state since it's unique.
    if challenge_part:
        await redis_cache.client.setex(
            f"oauth_pkce_challenge:{state}", _OAUTH_STATE_TTL, challenge_part
        )
    return True


def _sha256_b64url(data: str) -> str:
    """SHA-256(data), base64url, no padding — PKCE S256 transform."""
    digest = hashlib.sha256(data.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


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
            "client_name": "GAIA",
            "client_uri": "https://heygaia.com",
            "logo_uri": f"{base_url}/static/logo.png",
            "redirect_uris": [f"{base_url}/api/v1/mcp/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            # MUST be "none" - no client secrets allowed per spec Section 4.1
            "token_endpoint_auth_method": "none",  # nosec B105 - OAuth spec requires literal "none"
        },
        media_type="application/json",
    )


@router.get("/login/workos")
async def login_workos(return_url: Optional[str] = None):
    """
    Start the WorkOS SSO authentication flow.

    Args:
        return_url: Optional URL to redirect to after authentication.

    Returns:
        RedirectResponse: Redirects the user to the WorkOS SSO authorization URL
    """
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
    await redis_cache.client.setex(
        f"mobile_redirect:{state}", MOBILE_REDIRECT_TTL, redirect_uri
    )


async def _get_and_delete_mobile_redirect(state: str) -> str | None:
    """Get and delete mobile redirect URI from Redis (consume once)."""
    key = f"mobile_redirect:{state}"
    uri = await redis_cache.client.get(key)
    if uri:
        await redis_cache.client.delete(key)
    return uri


@router.get("/login/workos/mobile")
async def login_workos_mobile(
    redirect_uri: Optional[str] = None,
    code_challenge: Optional[str] = None,
):
    """
    Start WorkOS SSO flow for mobile apps (Expo).

    Args:
        redirect_uri: The deep link URI to redirect back to (from Linking.createURL)
        code_challenge: PKCE S256 challenge (H11). The client generates a
            random ``code_verifier``, sends ``SHA256(code_verifier)`` here,
            and presents the verifier again at ``/oauth/exchange-code``.
    """
    # Generate a unique state to track this auth flow. Doubles as both the
    # CSRF binding and the Redis key for the redirect URI.
    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, OAUTH_FLOW_MOBILE, code_challenge=code_challenge)

    # Store the mobile app's redirect URI
    # Default to gaiamobile:// scheme if not provided
    mobile_callback = redirect_uri or MOBILE_DEEP_LINK
    await _store_mobile_redirect(state, mobile_callback)

    log.set(oauth_flow_type=OAUTH_FLOW_MOBILE)
    log.info(
        f"Mobile OAuth started with redirect_uri: {mobile_callback}, state: {state[:8]}..."
    )

    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_MOBILE_REDIRECT_URI,
        state=state,
    )
    return {"url": authorization_url}


@router.get("/workos/mobile/callback")
async def workos_mobile_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
) -> RedirectResponse:
    """
    Handle WorkOS SSO callback for mobile (Expo) apps.
    Returns a deep link redirect to the mobile app carrying a one-time
    exchange code (never the sealed session itself — see C5).
    """
    # Get the stored redirect URI for this auth flow
    mobile_redirect: str | None = None
    if state:
        mobile_redirect = await _get_and_delete_mobile_redirect(state)

    if not mobile_redirect:
        mobile_redirect = MOBILE_DEEP_LINK
        log.warning(
            f"No stored redirect URI for state, using default: {mobile_redirect}"
        )

    log.set(oauth_flow_type=OAUTH_FLOW_MOBILE)
    log.info(f"Mobile OAuth callback, redirecting to: {mobile_redirect}")

    # CSRF binding: state must have been issued by our own /login endpoint
    # for this flow. Without this, an attacker can hand a victim a crafted
    # callback URL and complete login as the attacker's account.
    if not await _consume_oauth_state(state or "", OAUTH_FLOW_MOBILE):
        log.warning("Mobile OAuth state missing/invalid — rejecting callback")
        return RedirectResponse(url=f"{mobile_redirect}?error=invalid_state")

    try:
        if not code:
            log.error("No authorization code received from WorkOS (mobile)")
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

        token = auth_response.sealed_session or auth_response.access_token
        challenge = await redis_cache.client.get(f"oauth_pkce_challenge:{state}")
        if challenge:
            await redis_cache.client.delete(f"oauth_pkce_challenge:{state}")
        exchange_code = await _store_oauth_exchange_code(token, challenge)
        return RedirectResponse(url=f"{mobile_redirect}?code={exchange_code}")

    except HTTPException as e:
        log.error(f"HTTP error during WorkOS mobile auth: {e.detail}")
        return RedirectResponse(url=f"{mobile_redirect}?error={e.detail}")

    except Exception as e:
        log.error(f"Unexpected error during WorkOS mobile callback: {str(e)}")
        return RedirectResponse(
            url=f"{settings.WORKOS_MOBILE_REDIRECT_URI}?error=server_error"
        )


@router.get("/login/workos/desktop")
async def login_workos_desktop(code_challenge: Optional[str] = None):
    """
    Start the WorkOS SSO authentication flow for desktop app.
    Uses gaia:// protocol for callback redirect.

    Args:
        code_challenge: Optional PKCE S256 challenge (H11). The desktop app
            generates a random ``code_verifier``, sends
            ``SHA256(code_verifier)`` here, and presents the verifier
            again at ``/oauth/exchange-code`` to defeat on-device URL
            handler interception.
    """
    # CSRF-binding state: without this, any attacker can craft a
    # gaia://auth/callback URL and trick the desktop app into completing
    # login as the attacker's account.
    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, OAUTH_FLOW_DESKTOP, code_challenge=code_challenge)

    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_DESKTOP_REDIRECT_URI,
        state=state,
    )

    return RedirectResponse(url=authorization_url)


@router.get("/workos/desktop/callback")
async def workos_desktop_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
) -> RedirectResponse:
    """
    Handle the WorkOS SSO callback for desktop app.
    Redirects to gaia:// protocol with a short-lived one-time code that the
    desktop app exchanges for the sealed session via POST /oauth/exchange-code.
    """
    log.set(oauth_flow_type=OAUTH_FLOW_DESKTOP)

    if not await _consume_oauth_state(state or "", OAUTH_FLOW_DESKTOP):
        log.warning("Desktop OAuth state missing/invalid — rejecting callback")
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?error=invalid_state")

    try:
        # Validate code parameter
        if not code:
            log.error("No authorization code received from WorkOS (desktop)")
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

        token = auth_response.sealed_session or auth_response.access_token
        challenge = await redis_cache.client.get(f"oauth_pkce_challenge:{state}")
        if challenge:
            await redis_cache.client.delete(f"oauth_pkce_challenge:{state}")
        exchange_code = await _store_oauth_exchange_code(token, challenge)
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?code={exchange_code}")

    except HTTPException as e:
        log.error(f"HTTP error during WorkOS desktop auth: {e.detail}")
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?error={e.detail}")

    except Exception as e:
        log.error(f"Unexpected error during WorkOS desktop callback: {str(e)}")
        return RedirectResponse(url=f"{DESKTOP_DEEP_LINK}?error=server_error")


class ExchangeCodeRequest(BaseModel):
    """Body for the one-time code -> session exchange."""

    code: str
    # RFC 7636 PKCE (H11). Optional for backwards-compat, but when the
    # login endpoint received a code_challenge this field becomes required.
    code_verifier: Optional[str] = None


@router.post("/oauth/exchange-code")
async def exchange_oauth_code(body: ExchangeCodeRequest) -> JSONResponse:
    """Exchange a short-lived one-time ``code`` for the sealed WorkOS session.

    Replaces the old pattern of handing the sealed session back in the deep
    link query string, which leaked into reverse-proxy logs, APM
    breadcrumbs, and Referer headers. The client POSTs the code over TLS
    and receives the session in the JSON response body instead.

    If the original ``/login/workos/...`` call supplied ``code_challenge``
    (PKCE), the client MUST also supply the matching ``code_verifier``
    here. This defeats on-device URL-handler interception: even if a
    malicious app on the user's device receives the ``gaia://`` redirect
    and gets the one-time code, it cannot present the verifier that only
    the legitimate app generated.
    """
    token = await _consume_oauth_exchange_code(body.code, body.code_verifier)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return JSONResponse(content={"token": token})


@router.get("/workos/callback")
async def workos_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
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

    log.set(oauth_flow_type=OAUTH_FLOW_WEB)
    try:
        # Validate code parameter
        if not code:
            log.error("No authorization code received from WorkOS")
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

        # Redirect to return_url if provided, otherwise default /redirect
        destination = return_url or f"{settings.FRONTEND_URL}/redirect"
        # Ensure return_url is a relative path on our frontend (prevent open redirect)
        if return_url and not return_url.startswith("/"):
            destination = f"{settings.FRONTEND_URL}/redirect"
        else:
            destination = (
                f"{settings.FRONTEND_URL}{return_url}"
                if return_url
                else f"{settings.FRONTEND_URL}/redirect"
            )

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
        log.error(f"HTTP error during WorkOS : {e.detail}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error={e.detail}")

    except Exception as e:
        log.error(f"Unexpected error during WorkOS callback: {str(e)}")
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
        log.error(f"Invalid OAuth state token: {state}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/redirect?oauth_error=invalid_state"
        )

    redirect_path = state_data["redirect_path"]
    expected_user_id = state_data["user_id"]

    # Handle failed connection early
    if status != "success":
        error_type = "cancelled" if error == "access_denied" else "failed"
        log.warning(
            f"Composio connection failed: status={status}, error={error}, accountId={connectedAccountId}"
        )
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error={error_type}"
        )

    # Ensure we have connectedAccountId for success status
    if not connectedAccountId:
        log.error("Connected account ID missing for successful connection")
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
            log.error(f"Connected account not found: {connectedAccountId}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
            )

        # Extract essential information
        config_id = connected_account.auth_config.id
        user_id = connected_account.user_id  # type: ignore

        if not user_id:
            log.error(f"User ID missing for account: {connectedAccountId}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
            )

        # Find integration configuration by auth config ID
        integration_config = get_integration_by_config(config_id)
        if not integration_config:
            log.error(f"Integration config not found for auth_config_id: {config_id}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}{redirect_path}?oauth_error=failed"
            )

        log.set(
            user={"id": str(user_id)},
            integration_id=integration_config.id if integration_config else None,
        )

        # Verify user_id matches the state token (security check)
        if str(user_id) != expected_user_id:
            log.error(f"User ID mismatch: state={expected_user_id}, account={user_id}")
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
        log.info(
            f"Composio connection successful: user={user_id}, "
            f"integration={integration_config.id}, account={connectedAccountId}"
        )
        # Add success parameter and integration name to URL
        separator = "?" if "?" not in redirect_path else "&"
        redirect_url = f"{settings.FRONTEND_URL}/{redirect_path}{separator}oauth_success=true&integration={integration_config.id}"
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        log.error(
            f"Unexpected error in Composio callback: {str(e)}, "
            f"accountId={connectedAccountId}",
            exc_info=True,
        )
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
        )
