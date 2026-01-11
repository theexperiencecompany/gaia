import io
from typing import List, cast
from urllib.parse import urlencode

import cloudinary
import cloudinary.uploader
import httpx
from fastapi import HTTPException

from app.config.loggers import auth_logger as logger
from app.config.settings import settings
from app.config.token_repository import token_repository

http_async_client = httpx.AsyncClient()


async def build_google_oauth_url(
    user_email: str,
    state_token: str,
    integration_scopes: List[str],
    user_id: str | None = None,
) -> str:
    """
    Build a Google OAuth authorization URL with proper scope handling.

    Args:
        user_email: User's email for login hint
        state_token: OAuth state token for CSRF protection
        integration_scopes: New scopes to request for this integration
        user_id: Optional user ID to fetch existing scopes

    Returns:
        Complete Google OAuth authorization URL
    """
    # Base scopes always required
    base_scopes = ["openid", "profile", "email"]

    # Get existing scopes from user's current token
    existing_scopes: List[str] = []
    if user_id:
        try:
            token = await token_repository.get_token(
                str(user_id), "google", renew_if_expired=False
            )
            if token:
                existing_scopes = str(token.get("scope", "")).split()
        except Exception as e:
            logger.debug(f"Could not get existing scopes for user {user_id}: {e}")

    # Combine all scopes (base + existing + new), removing duplicates
    all_scopes = list(set(base_scopes + existing_scopes + integration_scopes))

    params = {
        "response_type": "code",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_CALLBACK_URL,
        "scope": " ".join(all_scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "login_hint": user_email,
        "state": state_token,
    }
    return f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"


async def upload_user_picture(image_bytes: bytes, public_id: str) -> str:
    """
    Uploads image bytes to Cloudinary and returns the secure URL.

    Args:
        image_bytes (bytes): The raw image data.
        public_id (str): The public ID to assign to the uploaded image.

    Returns:
        str: The secure URL of the uploaded image.

    Raises:
        HTTPException: If the upload to Cloudinary fails.
    """
    try:
        upload_result = cloudinary.uploader.upload(
            io.BytesIO(image_bytes),
            resource_type="image",
            public_id=public_id,
            overwrite=True,
        )
        image_url = upload_result.get("secure_url")
        if not image_url:
            logger.error("Missing secure_url in Cloudinary upload response")
            raise HTTPException(
                status_code=500, detail="Invalid response from image service"
            )

        logger.info(f"Image uploaded successfully. URL: {image_url}")
        return image_url
    except Exception as e:
        logger.error(f"Failed to upload image to Cloudinary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Image upload failed")


async def fetch_user_info_from_google(access_token: str):
    try:
        response = await http_async_client.get(
            settings.GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        logger.error(f"Error fetching user info: {e}")
        raise HTTPException(status_code=500, detail="Error contacting Google API")


async def get_tokens_from_code(code: str):
    try:
        response = await http_async_client.post(
            settings.GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_CALLBACK_URL,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        logger.error(f"Error fetching tokens: {e}")
        raise HTTPException(status_code=500, detail="Error contacting Google API")


async def get_tokens_by_user_id(user_id: str) -> tuple[str, str, bool]:
    """
    Get valid access and refresh tokens for the user by user ID.
    Uses the token repository to fetch and refresh tokens.

    Args:
        user_id: The user's ID

    Returns:
        tuple: (access_token, refresh_token, success_flag)
    """
    try:
        # Get token from repository
        token = await token_repository.get_token(user_id, "google")

        if not token:
            logger.error(f"No token found in repository for user: {user_id}")
            return "", "", False

        # Check if token needs refresh
        access_token = cast(str, token.get("access_token", ""))
        refresh_token = cast(str, token.get("refresh_token", ""))

        if not refresh_token:
            logger.error(f"Missing refresh token for user: {user_id}")
            return "", "", False

        # Check if token needs to be refreshed
        if not token.is_expired():
            # Token is still valid, return it
            return access_token, refresh_token, True

        # Token is expired, try to refresh it
        refreshed_token = await token_repository.refresh_token(user_id, "google")

        if not refreshed_token:
            logger.error(f"Failed to refresh token for user: {user_id}")
            return "", refresh_token, False

        new_access_token = cast(str, refreshed_token.get("access_token", ""))
        new_refresh_token = cast(str, refreshed_token.get("refresh_token", ""))

        return new_access_token, new_refresh_token, True

    except Exception as e:
        logger.error(f"Error getting tokens for user {user_id}: {str(e)}")
        return "", "", False
