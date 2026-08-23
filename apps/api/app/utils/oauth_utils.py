import io
from urllib.parse import urlencode

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException
import httpx

from app.config.settings import settings
from app.config.token_repository import token_repository
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

http_async_client = httpx.AsyncClient()


async def build_google_oauth_url(
    user_email: str,
    state_token: str,
    integration_scopes: list[str],
    user_id: str | None = None,
) -> str:
    log.set(
        operation="build_google_oauth_url",
        user_email=user_email,
        requested_scopes=integration_scopes,
        user_id=user_id,
    )
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
    existing_scopes: list[str] = []
    if user_id:
        try:
            token = await token_repository.get_token(str(user_id), "google", renew_if_expired=False)
            if token:
                existing_scopes = (token.get("scope") or "").split()
        except Exception as e:
            log.debug(
                f"{LogTag.OAUTH} Could not get existing scopes for user",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

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
    log.set(operation="upload_user_picture")
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
        image_url: str | None = upload_result.get("secure_url")
        if not image_url:
            log.error(f"{LogTag.OAUTH} Missing secure_url in Cloudinary upload response")
            raise HTTPException(status_code=500, detail="Invalid response from image service")

        log.info(f"{LogTag.OAUTH} Image uploaded successfully. URL", image_url=image_url)
        return image_url
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to upload image to Cloudinary",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Image upload failed") from e
