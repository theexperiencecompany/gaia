from datetime import datetime, timezone
from typing import Optional

import pytz
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.models.user_models import UserUpdateResponse
from app.services.onboarding_service import get_user_onboarding_status
from app.services.user_service import update_user_profile
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
from fastapi.responses import JSONResponse
from workos import WorkOSClient

router = APIRouter()

workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


@router.get("/me", response_model=dict)
async def get_me(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Returns the current authenticated user's details.
    Uses the dependency injection to fetch user data.
    """
    # Get onboarding status
    onboarding_status = await get_user_onboarding_status(user["user_id"])

    return {
        "message": "User retrieved successfully",
        **user,
        "onboarding": onboarding_status,
    }


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


@router.get("/holo-card/{card_id}")
async def get_public_holo_card(card_id: str):
    """
    Get public holo card data by card ID (user ID).
    This endpoint is public and doesn't require authentication.
    Returns basic profile info without sensitive data like workflows.
    """
    try:
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
