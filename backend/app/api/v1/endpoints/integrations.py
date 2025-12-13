from functools import lru_cache
from urllib.parse import urlencode

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_id,
    get_integration_scopes,
)
from app.config.settings import settings
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.models.oauth_models import IntegrationConfigResponse
from app.services.composio.composio_service import (
    COMPOSIO_SOCIAL_CONFIGS,
    get_composio_service,
)
from app.services.oauth_service import get_all_integrations_status
from app.services.oauth_state_service import create_oauth_state
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter()


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
                f"integrations/login/{integration.id}"
                if integration.available
                else None
            ),
            isSpecial=integration.is_special,
            displayPriority=integration.display_priority,
            includedIntegrations=integration.included_integrations,
            isFeatured=integration.is_featured,
        )
        integration_configs.append(config.model_dump())

    return {"integrations": integration_configs}


@router.get("/config")
async def get_integrations_config():
    """
    Get the configuration for all integrations.
    This endpoint is public and returns integration metadata.
    Uses lru_cache for improved performance.
    """
    cached_config = _build_integrations_config()
    return JSONResponse(content=cached_config)


@router.get("/status")
async def get_integrations_status(
    user: dict = Depends(get_current_user),
):
    """
    Get the integration status for the current user based on OAuth scopes.
    """
    try:
        user_id = user.get("user_id")

        if not user_id:
            logger.warning("User ID not found in user object")
            return JSONResponse(
                content={"integrations": [], "debug": {"error": "User ID not found"}},
                status_code=400,
            )

        # Use unified status checker for all integrations
        status_map = await get_all_integrations_status(str(user_id))

        # Build integration statuses
        integration_statuses = [
            {
                "integrationId": integration_id,
                "connected": status_map.get(integration_id, False),
            }
            for integration_id in status_map.keys()
        ]

        return JSONResponse(
            content={
                "integrations": integration_statuses,
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


@router.delete("/{integration_id}")
async def disconnect_integration(
    integration_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Disconnect a connected integration for the current user.
    Only supports Composio-managed integrations.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    integration = get_integration_by_id(integration_id)
    if not integration:
        raise HTTPException(
            status_code=404, detail=f"Integration {integration_id} not found"
        )

    if integration.managed_by == "composio":
        composio_service = get_composio_service()
        try:
            await composio_service.delete_connected_account(
                user_id=str(user_id), provider=integration.provider
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(
                f"Error disconnecting integration {integration_id} for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to disconnect integration"
            )

    elif integration.managed_by == "self":
        # Handle internal disconnection by revoking the token
        try:
            # For internal integrations, the provider in config matches the provider in token repo
            success = await token_repository.revoke_token(
                user_id=str(user_id), provider=integration.provider
            )
            if not success:
                # If token not found, consider it already disconnected
                logger.warning(
                    f"Attempted to disconnect {integration_id} but no token found for user {user_id}"
                )
        except Exception as e:
            logger.error(
                f"Error disconnecting internal integration {integration_id} for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to disconnect integration"
            )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Integration {integration_id} disconnect not supported.",
        )

    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"OAuth status cache invalidated for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate OAuth status cache: {e}")

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Successfully disconnected {integration.name}",
            "integrationId": integration_id,
        }
    )


@router.get("/login/{integration_id}")
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

    # Create secure state token for OAuth flow
    state_token = await create_oauth_state(
        user_id=user["user_id"],
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    # Streamlined composio integration handling
    composio_providers = set([k for k in COMPOSIO_SOCIAL_CONFIGS.keys()])
    if integration.provider in composio_providers:
        provider_key = integration.provider
        url = await composio_service.connect_account(
            provider_key, user["user_id"], state_token=state_token
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
            "state": state_token,  # Secure state token for CSRF protection
        }
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
        return RedirectResponse(url=auth_url)

    raise HTTPException(
        status_code=400,
        detail=f"OAuth provider {integration.provider} not implemented",
    )
