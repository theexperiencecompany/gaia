from app.config.settings import settings
from fastapi import Header, HTTPException, status


async def verify_bot_api_key(
    x_bot_api_key: str = Header(..., alias="X-Bot-API-Key"),
) -> None:
    """Verify bot API key from request header."""
    bot_api_key = getattr(settings, "GAIA_BOT_API_KEY", None)
    if not bot_api_key or x_bot_api_key != bot_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bot API key",
        )
