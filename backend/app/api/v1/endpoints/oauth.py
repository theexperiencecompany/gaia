from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional
from urllib.parse import urlencode

import httpx
import pytz
from bson import ObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse
from workos import WorkOSClient

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_config,
    get_integration_by_id,
    get_integration_scopes,
)
from app.config.settings import settings
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.db.redis import delete_cache
from app.models.oauth_models import IntegrationConfigResponse
from app.models.user_models import (
    BioStatus,
    OnboardingPhaseUpdateRequest,
    OnboardingPreferences,
    OnboardingRequest,
    OnboardingResponse,
    UserUpdateResponse,
)
from app.services.composio.composio_service import (
    COMPOSIO_SOCIAL_CONFIGS,
    get_composio_service,
)
from app.services.oauth_service import store_user_info
from app.services.onboarding_service import (
    complete_onboarding,
    get_user_onboarding_status,
    update_onboarding_preferences,
)
from app.services.user_service import update_user_profile
from app.utils.oauth_utils import fetch_user_info_from_google, get_tokens_from_code
from app.utils.redis_utils import RedisPoolManager

router = APIRouter()
http_async_client = httpx.AsyncClient()

workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


async def _queue_gmail_processing(user_id: str) -> None:
    """Queue Gmail email processing as an ARQ background task."""
    try:
        pool = await RedisPoolManager.get_pool()
        job = await pool.enqueue_job("process_gmail_emails_to_memory", user_id)

        if job:
            logger.info(
                f"Queued Gmail processing for user {user_id} with job ID {job.job_id}"
            )
        else:
            logger.error(f"Failed to queue Gmail processing for user {user_id}")

    except Exception as e:
        logger.error(f"Error queuing Gmail processing for user {user_id}: {e}")


async def _queue_personalization(user_id: str) -> None:
    """Queue post-onboarding personalization as an ARQ background task."""
    try:
        pool = await RedisPoolManager.get_pool()
        job = await pool.enqueue_job("process_personalization_task", user_id)

        if job:
            logger.info(
                f"Queued personalization for user {user_id} with job ID {job.job_id}"
            )
        else:
            logger.error(f"Failed to queue personalization for user {user_id}")

    except Exception as e:
        logger.error(f"Error queuing personalization for user {user_id}: {e}")


@lru_cache(maxsize=1)
def _build_integrations_config():
    """
    Build and cache the integrations configuration response.
    This function is cached using lru_cache for performance.
    """
    integration_configs = []
    for integration in OAUTH_INTEGRATIONS:
        config = IntegrationConfigResponse(
            id=integration.id,
            name=integration.name,
            description=integration.description,
            category=integration.category,
            provider=integration.provider,
            available=integration.available,
            loginEndpoint=(
                f"oauth/login/integration/{integration.id}"
                if integration.available
                else None
            ),
            isSpecial=integration.is_special,
            displayPriority=integration.display_priority,
            includedIntegrations=integration.included_integrations,
        )
        integration_configs.append(config.model_dump())

    return {"integrations": integration_configs}


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


@router.get("/workos/callback")
async def workos_callback(
    code: Optional[str] = None,
) -> RedirectResponse:
    """
    Handle the WorkOS SSO callback.

    Args:config_id
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


@router.get("/login/integration/{integration_id}")
async def login_integration(
    integration_id: str,
    redirect_path: str,
    user: dict = Depends(get_current_user),
):
    """Dynamic OAuth login for any configured integration."""
    integration = get_integration_by_id(integration_id)
    composio_service = get_composio_service()

    if not integration:
        raise HTTPException(
            status_code=404, detail=f"Integration {integration_id} not found"
        )

    if not integration.available:
        raise HTTPException(
            status_code=400, detail=f"Integration {integration_id} is not available yet"
        )

    # Streamlined composio integration handling
    composio_providers = set([k for k in COMPOSIO_SOCIAL_CONFIGS.keys()])
    if integration.provider in composio_providers:
        provider_key = integration.provider
        url = await composio_service.connect_account(
            provider_key, user["user_id"], frontend_redirect_path=redirect_path
        )
        return RedirectResponse(url=url["redirect_url"])
    elif integration.provider == "google":
        # Get base scopes
        base_scopes = ["openid", "profile", "email"]

        # Get new integration scopes
        new_scopes = get_integration_scopes(integration_id)

        # Get existing scopes from user's current token
        existing_scopes = []
        user_id = user.get("user_id")

        if user_id:
            try:
                token = await token_repository.get_token(
                    str(user_id), "google", renew_if_expired=False
                )
                existing_scopes = str(token.get("scope", "")).split()
            except Exception as e:
                logger.warning(f"Could not get existing scopes: {e}")

        # Combine all scopes (base + existing + new), removing duplicates
        all_scopes = list(set(base_scopes + existing_scopes + new_scopes))

        params = {
            "response_type": "code",
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_CALLBACK_URL,
            "scope": " ".join(all_scopes),
            "access_type": "offline",
            "prompt": "consent",  # Only force consent for additional scopes
            "include_granted_scopes": "true",  # Include previously granted scopes
            "login_hint": user.get("email"),
        }
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
        return RedirectResponse(url=auth_url)

    raise HTTPException(
        status_code=400,
        detail=f"OAuth provider {integration.provider} not implemented",
    )


@router.get("/composio/callback", response_class=RedirectResponse)
async def composio_callback(
    status: str,
    frontend_redirect_path: str,
    background_tasks: BackgroundTasks,
    connectedAccountId: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Handle Composio OAuth callback after successful/failed connection.

    Args:
        status: Connection status from Composio ('success' or 'failed')
        frontend_redirect_path: Path to redirect user after processing
        background_tasks: FastAPI background tasks for async operations
        connectedAccountId: Unique identifier for the connected account (optional for failures)
        error: Error code from OAuth provider (optional)

    Returns:
        RedirectResponse: Redirects user to frontend with appropriate status
    """
    # Handle failed connection early
    if status != "success":
        error_type = "cancelled" if error == "access_denied" else "failed"
        logger.warning(
            f"Composio connection failed: status={status}, error={error}, accountId={connectedAccountId}"
        )
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/{frontend_redirect_path}?oauth_error={error_type}"
        )

    # Ensure we have connectedAccountId for success status
    if not connectedAccountId:
        logger.error("Connected account ID missing for successful connection")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/{frontend_redirect_path}?oauth_error=failed"
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
                url=f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
            )

        # Setup triggers if available
        if integration_config.associated_triggers:
            logger.info(
                f"Setting up {len(integration_config.associated_triggers)} triggers "
                f"for user {user_id} and integration {integration_config.id}"
            )
            background_tasks.add_task(
                composio_service.handle_subscribe_trigger,
                user_id=user_id,
                triggers=integration_config.associated_triggers,
            )

        # Process Gmail emails to memory if this is a Gmail connection
        if integration_config.id == "gmail":
            logger.info(f"Starting Gmail email processing for user {user_id}")

            # Check if user has completed onboarding and update bio_status to processing
            try:
                user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
                if user_doc and user_doc.get("onboarding", {}).get("completed"):
                    current_bio_status = user_doc.get("onboarding", {}).get(
                        "bio_status"
                    )

                    # If bio was generated without Gmail, update status to processing
                    if current_bio_status in [BioStatus.NO_GMAIL, "no_gmail"]:
                        await users_collection.update_one(
                            {"_id": ObjectId(user_id)},
                            {
                                "$set": {
                                    "onboarding.bio_status": BioStatus.PROCESSING,
                                    "updated_at": datetime.now(timezone.utc),
                                }
                            },
                        )
                        logger.info(
                            f"Updated bio_status to processing for user {user_id} "
                            f"(was {current_bio_status})"
                        )

                        # Send WebSocket update to notify frontend
                        try:
                            await websocket_manager.send_to_user(
                                user_id=user_id,
                                message={
                                    "type": "bio_status_update",
                                    "data": {"bio_status": BioStatus.PROCESSING},
                                },
                            )
                        except Exception as ws_error:
                            logger.warning(
                                f"Failed to send WebSocket update: {ws_error}"
                            )
            except Exception as e:
                logger.error(
                    f"Error updating bio_status for user {user_id}: {e}", exc_info=True
                )

            background_tasks.add_task(_queue_gmail_processing, user_id)

        # Invalidate OAuth status cache for this user
        try:
            cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
            await delete_cache(cache_key)
            logger.info(f"OAuth status cache invalidated for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate OAuth status cache: {e}")

        # Successful connection - redirect to frontend with success indicator
        logger.info(
            f"Composio connection successful: user={user_id}, "
            f"integration={integration_config.id}, account={connectedAccountId}"
        )
        # Add oauth_success parameter to inform frontend of successful connection
        separator = "&" if "?" in frontend_redirect_path else "?"
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/{frontend_redirect_path}{separator}oauth_success=true"
        )

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
    error: Optional[str] = None,
) -> RedirectResponse:
    try:
        # Handle OAuth errors (e.g., user canceled)
        if error:
            logger.warning(f"OAuth error: {error}")
            if error == "access_denied":
                # User canceled OAuth flow
                redirect_url = f"{settings.FRONTEND_URL}/redirect?oauth_error=cancelled"
            else:
                # Other OAuth errors
                redirect_url = f"{settings.FRONTEND_URL}/redirect?oauth_error={error}"
            return RedirectResponse(url=redirect_url)

        # Check if we have the authorization code
        if not code:
            logger.error("No authorization code provided")
            redirect_url = f"{settings.FRONTEND_URL}/redirect?oauth_error=no_code"
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

        # Redirect URL can include tokens if needed
        redirect_url = f"{settings.FRONTEND_URL}/redirect"
        response = RedirectResponse(url=redirect_url)

        return response

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/me", response_model=dict)
async def get_me(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Returns the current authenticated user's details.
    Uses the dependency injection to fetch user data.
    """
    # fetch_last_week_emails.delay(user)

    # Get onboarding status
    onboarding_status = await get_user_onboarding_status(user["user_id"])

    return {
        "message": "User retrieved successfully",
        **user,
        "onboarding": onboarding_status,
    }


@router.get("/integrations/config")
async def get_integrations_config():
    """
    Get the configuration for all integrations.
    This endpoint is public and returns integration metadata.
    Uses lru_cache for improved performance.
    """
    cached_config = _build_integrations_config()
    return JSONResponse(content=cached_config)


@router.get("/integrations/status")
async def get_integrations_status(
    user: dict = Depends(get_current_user),
):
    """
    Get the integration status for the current user based on OAuth scopes.
    """
    composio_service = get_composio_service()
    try:
        authorized_scopes = []
        user_id = user.get("user_id")

        # Get token from repository for Google integrations
        try:
            if not user_id:
                logger.warning("User ID not found in user object")
                raise ValueError("User ID not found")

            token = await token_repository.get_token(
                str(user_id), "google", renew_if_expired=True
            )
            authorized_scopes = str(token.get("scope", "")).split()
        except Exception as e:
            logger.warning(f"Error retrieving token from repository: {e}")
            # Continue with empty scopes

        # Batch check Composio providers
        composio_status = {}
        composio_status = await composio_service.check_connection_status(
            list(COMPOSIO_SOCIAL_CONFIGS.keys()), str(user_id)
        )

        # Build integration statuses
        integration_statuses = []
        for integration in OAUTH_INTEGRATIONS:
            if integration.provider in composio_status:
                # Use Composio status
                is_connected = composio_status[integration.provider]
            elif integration.provider == "google" and authorized_scopes:
                # Check Google OAuth scopes
                required_scopes = get_integration_scopes(integration.id)
                is_connected = all(
                    scope in authorized_scopes for scope in required_scopes
                )
            else:
                is_connected = False

            integration_statuses.append(
                {"integrationId": integration.id, "connected": is_connected}
            )

        return JSONResponse(
            content={
                "integrations": integration_statuses,
                "debug": {
                    "authorized_scopes": authorized_scopes,
                },
            }
        )

    except Exception as e:
        logger.error(f"Error checking integration status: {e}")
        # Return all disconnected on error
        return JSONResponse(
            content={
                "integrations": [
                    {"integrationId": i.id, "connected": False}
                    for i in OAUTH_INTEGRATIONS
                ]
            }
        )


@router.patch("/me", response_model=UserUpdateResponse)
async def update_me(
    name: Optional[str] = Form(None),
    picture: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    """
    Update the current user's profile information.
    Supports updating name and profile picture.
    """
    user_id = user.get("user_id")

    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    # Process profile picture if provided
    picture_data = None
    if picture and picture.size and picture.size > 0:
        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if picture.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}",
            )

        # Validate file size (max 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        if picture.size > max_size:
            raise HTTPException(
                status_code=400, detail="File size too large. Maximum size is 5MB"
            )

        picture_data = await picture.read()

    # Update user profile
    updated_user = await update_user_profile(
        user_id=user_id, name=name, picture_data=picture_data
    )

    return UserUpdateResponse(**updated_user)


@router.post("/onboarding", response_model=OnboardingResponse)
async def complete_user_onboarding(
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tz_info: GET_USER_TZ_TYPE = Depends(get_user_timezone),
):
    """
    Complete user onboarding by storing preferences.

    Flow:
    - If user has Gmail connected: Email processor will trigger personalization after parsing
    - If no Gmail: Queue personalization ARQ job directly
    """
    try:
        updated_user = await complete_onboarding(
            user["user_id"], onboarding_data, user_timezone=tz_info[0]
        )

        # Check if user has Gmail connected via Composio
        from app.services.composio.composio_service import get_composio_service

        composio_service = get_composio_service()
        connection_status = await composio_service.check_connection_status(
            ["gmail"], user["user_id"]
        )
        has_gmail = connection_status.get("gmail", False)

        if has_gmail:
            logger.info(
                f"User {user['user_id']} has Gmail - personalization will run after email processing"
            )
        else:
            # No Gmail, queue personalization directly
            logger.info(
                f"User {user['user_id']} has no Gmail - queueing personalization directly"
            )
            background_tasks.add_task(_queue_personalization, user["user_id"])

        return OnboardingResponse(
            success=True, message="Onboarding completed successfully", user=updated_user
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error completing onboarding: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to complete onboarding")


@router.get("/onboarding/status", response_model=dict)
async def get_onboarding_status(user: dict = Depends(get_current_user)):
    """
    Get the current user's onboarding status and preferences.
    """
    status = await get_user_onboarding_status(user["user_id"])
    return status


@router.post("/onboarding/phase", response_model=dict)
async def update_onboarding_phase(
    request: OnboardingPhaseUpdateRequest, user: dict = Depends(get_current_user)
):
    """
    Update the user's onboarding phase.
    Used to track progress through onboarding stages.
    """
    try:
        user_id = user.get("user_id")
        phase = request.phase.value

        logger.info(
            f"[update_onboarding_phase] Updating phase to {phase} for user {user_id}"
        )

        # Update the phase in database
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "onboarding.phase": request.phase.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.modified_count == 0:
            logger.warning(
                f"[update_onboarding_phase] No document modified for user {user_id}"
            )
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(
            f"[update_onboarding_phase] Successfully updated phase to {phase} for user {user_id}, modified_count={result.modified_count}"
        )

        # Send WebSocket notification about phase update
        try:
            from app.websocket.websocket_manager import websocket_manager

            await websocket_manager.send_to_user(
                user_id=user_id,
                message={
                    "type": "onboarding_phase_update",
                    "data": {"phase": phase},
                },
            )
            logger.info(
                f"[update_onboarding_phase] Sent WebSocket notification for phase update to {phase}"
            )
        except Exception as ws_error:
            logger.warning(
                f"[update_onboarding_phase] Failed to send WebSocket update: {ws_error}"
            )

        return {
            "success": True,
            "phase": phase,
            "message": f"Onboarding phase updated to {phase}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating onboarding phase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update onboarding phase")


@router.patch("/onboarding/preferences", response_model=dict)
async def update_user_preferences(
    preferences: OnboardingPreferences, user: dict = Depends(get_current_user)
):
    """
    Update user's onboarding preferences.
    This can be used from the settings page to update preferences after onboarding.
    """
    try:
        updated_user = await update_onboarding_preferences(user["user_id"], preferences)

        return {
            "success": True,
            "message": "Preferences updated successfully",
            "user": updated_user,
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating preferences: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update preferences")


@router.get("/onboarding/personalization")
async def get_onboarding_personalization(user: dict = Depends(get_current_user)):
    """
    Get personalization data (house, phrase, bio, workflows) for current authenticated user.
    Used as fallback if WebSocket fails or to refetch data.
    Returns default values if personalization hasn't completed yet.
    """
    try:
        from bson import ObjectId

        from app.db.mongodb.collections import users_collection, workflows_collection

        user_id = user.get("user_id")
        logger.info(
            f"[get_onboarding_personalization] Fetching personalization for user {user_id}"
        )
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})

        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding = user_doc.get("onboarding", {})
        user_bio = onboarding.get("user_bio", "")
        # Check the phase to determine if personalization is complete
        phase = onboarding.get("phase", "initial")
        logger.info(
            f"[get_onboarding_personalization] User {user_id} has phase: {phase}, bio_status: {onboarding.get('bio_status')}"
        )
        has_personalization = phase in [
            "personalization_complete",
            "getting_started",
            "completed",
        ]

        # Get stored metadata or calculate if not stored (for older users)
        account_number = onboarding.get("account_number")
        member_since = onboarding.get("member_since")

        if not account_number or not member_since:
            created_at = user_doc.get("created_at")
            if created_at:
                count = await users_collection.count_documents(
                    {"created_at": {"$lt": created_at}}
                )
                account_number = count + 1
            else:
                account_number = 1

            member_since = (
                created_at.strftime("%b %d, %Y") if created_at else "Nov 21, 2024"
            )

        # Fetch full workflow objects
        workflow_ids = onboarding.get("suggested_workflows", [])
        workflows = []
        for wf_id in workflow_ids:
            try:
                query_id = ObjectId(wf_id) if ObjectId.is_valid(wf_id) else wf_id
                wf = await workflows_collection.find_one({"_id": query_id})
                if wf:
                    workflows.append(
                        {
                            "id": str(wf["_id"]),
                            "title": wf.get("title", ""),
                            "description": wf.get("description", ""),
                            "steps": wf.get("steps", []),
                        }
                    )
            except Exception:
                continue

        # Determine what bio to show based on bio_status
        bio_status = onboarding.get("bio_status", "pending")
        display_bio = user_bio

        # Override bio display based on status
        if bio_status in ["processing", BioStatus.PROCESSING]:
            display_bio = "Processing your insights... Please check back in a moment."
        elif bio_status in ["pending", BioStatus.PENDING]:
            # Check if user has Gmail via Composio to show appropriate message
            from app.services.composio.composio_service import get_composio_service

            composio_service = get_composio_service()
            connection_status = await composio_service.check_connection_status(
                ["gmail"], str(user_id)
            )
            has_gmail = connection_status.get("gmail", False)
            if has_gmail:
                display_bio = (
                    "Processing your insights... Please check back in a moment."
                )
            else:
                display_bio = "Setting up your profile..."
        # For "no_gmail" and "completed" status, use the actual bio content
        # (no_gmail now has a default bio, completed has the full bio)

        return {
            "phase": phase,
            "has_personalization": has_personalization,
            "house": onboarding.get("house", "Bluehaven"),
            "personality_phrase": onboarding.get(
                "personality_phrase", "Curious Adventurer"
            ),
            "user_bio": display_bio,
            "account_number": account_number,
            "member_since": member_since,
            "overlay_color": onboarding.get("overlay_color", "rgba(0,0,0,0)"),
            "overlay_opacity": onboarding.get("overlay_opacity", 40),
            "suggested_workflows": workflows,
            "name": user_doc.get("name", "User"),
            "holo_card_id": str(user_doc["_id"]),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching personalization: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to fetch personalization data"
        )


@router.get("/holo-card/{card_id}")
async def get_public_holo_card(card_id: str):
    """
    Get public holo card data by card ID (user ID).
    This endpoint is public and doesn't require authentication.
    Returns basic profile info without sensitive data like workflows.
    """
    try:
        from bson import ObjectId

        from app.db.mongodb.collections import users_collection

        if not ObjectId.is_valid(card_id):
            raise HTTPException(status_code=400, detail="Invalid card ID")

        user_doc = await users_collection.find_one({"_id": ObjectId(card_id)})

        if not user_doc:
            raise HTTPException(status_code=404, detail="Card not found")

        onboarding = user_doc.get("onboarding", {})

        # Check if user has completed onboarding
        if not onboarding.get("house"):
            raise HTTPException(status_code=404, detail="Card not found")

        # Get stored metadata or calculate if not stored (for older users)
        account_number = onboarding.get("account_number")
        member_since = onboarding.get("member_since")

        if not account_number or not member_since:
            created_at = user_doc.get("created_at")
            if created_at:
                count = await users_collection.count_documents(
                    {"created_at": {"$lt": created_at}}
                )
                account_number = count + 1
            else:
                account_number = 1

            member_since = (
                created_at.strftime("%b %d, %Y") if created_at else "Nov 21, 2024"
            )

        return {
            "house": onboarding.get("house"),
            "personality_phrase": onboarding.get("personality_phrase"),
            "user_bio": onboarding.get("user_bio"),
            "account_number": account_number,
            "member_since": member_since,
            "name": user_doc.get("name"),
            "overlay_color": onboarding.get("overlay_color", "rgba(0,0,0,0)"),
            "overlay_opacity": onboarding.get("overlay_opacity", 40),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching holo card: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch holo card data")


@router.patch("/holo-card/colors")
async def update_holo_card_colors(
    overlay_color: str = Form(..., description="Overlay color or gradient"),
    overlay_opacity: int = Form(..., description="Overlay opacity (0-100)"),
    user: dict = Depends(get_current_user),
):
    """
    Update holo card overlay color and opacity.
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Validate opacity range
        if not 0 <= overlay_opacity <= 100:
            raise HTTPException(
                status_code=400, detail="Opacity must be between 0 and 100"
            )

        # Update user's onboarding data
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "onboarding.overlay_color": overlay_color,
                    "onboarding.overlay_opacity": overlay_opacity,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "success": True,
            "message": "Holo card colors updated successfully",
            "overlay_color": overlay_color,
            "overlay_opacity": overlay_opacity,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating holo card colors: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update holo card colors")


@router.patch("/timezone", response_model=dict)
async def update_user_timezone(
    user_timezone: str = Form(
        ...,
        description="User's timezone (e.g., 'America/New_York', 'Asia/Kolkata')",
        alias="timezone",
    ),
    user: dict = Depends(get_current_user),
):
    """
    Update user's timezone setting.
    This updates the root-level timezone field for the user.
    """
    try:
        try:
            pytz.timezone(user_timezone.strip())
        except pytz.UnknownTimeZoneError:
            if user_timezone.strip().upper() != "UTC":
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid timezone: {user_timezone}. Use standard timezone identifiers like 'America/New_York', 'UTC', 'Asia/Kolkata'",
                )

        result = await users_collection.update_one(
            {"_id": ObjectId(user["user_id"])},
            {
                "$set": {
                    "timezone": user_timezone.strip(),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "success": True,
            "message": "Timezone updated successfully",
            "timezone": user_timezone.strip(),
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating timezone: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update timezone")


@router.patch("/name", response_model=UserUpdateResponse)
async def update_user_name(
    name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """
    Update the user's name. This is the consolidated endpoint for name updates.
    """
    try:
        user_id = user.get("user_id")

        if not user_id or not isinstance(user_id, str):
            raise HTTPException(status_code=400, detail="Invalid user ID")

        updated_user = await update_user_profile(user_id=user_id, name=name)
        return UserUpdateResponse(**updated_user)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating user name: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update name")


@router.post("/logout")
async def logout(
    request: Request,
):
    """
    Logout user and return logout URL for frontend redirection.
    """
    wos_session = request.cookies.get("wos_session")

    if not wos_session:
        raise HTTPException(status_code=401, detail="No active session")

    try:
        session = workos.user_management.load_sealed_session(
            sealed_session=wos_session,
            cookie_password=settings.WORKOS_COOKIE_PASSWORD,
        )

        if not session:
            raise HTTPException(status_code=401, detail="Invalid session")

        logout_url = session.get_logout_url()

        # Create response with logout URL
        response = JSONResponse(content={"logout_url": logout_url})

        # Clear the session cookie
        response.delete_cookie(
            "wos_session",
            httponly=True,
            path="/",
            secure=settings.ENV == "production",
            samesite="lax",
        )

        return response

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=500, detail="Logout failed")
