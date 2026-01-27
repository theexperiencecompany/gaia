"""
Linked Accounts API

Manages platform account linking for bots (Discord, Slack, Telegram).
These are identity links that allow users to interact with GAIA through external platforms.
This is separate from Integrations which provide service access (Gmail, Calendar, etc.).
"""

from datetime import datetime, timezone
from urllib.parse import urlencode

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.services.oauth.oauth_state_service import create_oauth_state
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

router = APIRouter()


# Platform configurations for linked accounts
LINKED_PLATFORMS = {
    "discord": {
        "id": "discord",
        "name": "Discord",
        "description": "Chat with GAIA on Discord servers using our bot",
        "icon": "discord",
        "available": True,
    },
    "slack": {
        "id": "slack",
        "name": "Slack",
        "description": "Use GAIA in your Slack workspace",
        "icon": "slack",
        "available": False,  # Coming soon
    },
    "telegram": {
        "id": "telegram",
        "name": "Telegram",
        "description": "Message GAIA through Telegram",
        "icon": "telegram",
        "available": False,  # Coming soon
    },
}


class LinkedAccountStatus(BaseModel):
    """Status of a linked platform account."""

    platform: str
    linked: bool
    linked_at: datetime | None = None


class LinkedAccountsResponse(BaseModel):
    """Response containing all linked account statuses."""

    accounts: list[LinkedAccountStatus]


@router.get("/config")
async def get_linked_accounts_config():
    """
    Get configuration for all linkable platforms.
    This endpoint is public and returns platform metadata.
    """
    platforms = list(LINKED_PLATFORMS.values())
    return JSONResponse(content={"platforms": platforms})


@router.get("/status")
async def get_linked_accounts_status(
    user: dict = Depends(get_current_user),
):
    """
    Get the linked account status for all platforms for the current user.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
        platform_links = user_doc.get("platform_links", {}) if user_doc else {}

        accounts = []
        for platform_id, config in LINKED_PLATFORMS.items():
            platform_data = platform_links.get(platform_id)
            linked = bool(platform_data)
            linked_at = None

            if linked and isinstance(platform_data, dict):
                linked_at = platform_data.get("linked_at")

            accounts.append(
                {
                    "platform": platform_id,
                    "name": config["name"],
                    "description": config["description"],
                    "icon": config["icon"],
                    "available": config["available"],
                    "linked": linked,
                    "linkedAt": linked_at.isoformat() if linked_at else None,
                }
            )

        return JSONResponse(content={"accounts": accounts})

    except Exception as e:
        logger.error(f"Error getting linked accounts status: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get linked accounts status"
        )


@router.get("/link/{platform}")
async def link_platform(
    platform: str,
    redirect_path: str = "/settings?section=linked-accounts",
    user: dict = Depends(get_current_user),
):
    """
    Initiate OAuth flow to link a platform account.
    """
    if platform not in LINKED_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Platform {platform} not found")

    config = LINKED_PLATFORMS[platform]
    if not config["available"]:
        raise HTTPException(
            status_code=400, detail=f"Platform {platform} is not available yet"
        )

    # Create secure state token
    state_token = await create_oauth_state(
        user_id=user["user_id"],
        redirect_path=redirect_path,
        integration_id=f"linked_{platform}",
    )

    if platform == "discord":
        params = {
            "response_type": "code",
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": settings.DISCORD_CALLBACK_URL,
            "scope": "identify",
            "state": state_token,
        }
        auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
        return RedirectResponse(url=auth_url)

    # Add other platforms here as they become available
    raise HTTPException(status_code=400, detail=f"OAuth for {platform} not implemented")


@router.delete("/{platform}")
async def unlink_platform(
    platform: str,
    user: dict = Depends(get_current_user),
):
    """
    Unlink a platform account from the user's GAIA account.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    if platform not in LINKED_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Platform {platform} not found")

    try:
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$unset": {f"platform_links.{platform}": ""},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        if result.modified_count == 0:
            logger.warning(
                f"Attempted to unlink {platform} but no link found for user {user_id}"
            )

        logger.info(f"Unlinked {platform} account for user {user_id}")

        return JSONResponse(
            content={
                "status": "success",
                "message": f"Successfully unlinked {LINKED_PLATFORMS[platform]['name']}",
                "platform": platform,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unlinking {platform} for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to unlink platform")
