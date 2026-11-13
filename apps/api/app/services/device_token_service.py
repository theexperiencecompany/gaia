"""Device Token Service for Push Notifications."""

from app.db.repositories.device_tokens import device_token_repository
from app.models.device_token_models import PlatformType
from shared.py.wide_events import log


async def register_device_token(
    user_id: str,
    token: str,
    platform: PlatformType,
    device_id: str | None = None,
) -> bool:
    """Register or update a device token for push notifications. Returns success."""
    try:
        is_new = await device_token_repository.register(
            user_id=user_id, token=token, platform=platform, device_id=device_id
        )
        if is_new:
            log.set(
                device_token={
                    "user_id": user_id,
                    "platform": platform.value,
                    "action": "registered",
                }
            )
            log.info("Registered new device token for user", user_id=user_id)
        else:
            log.set(
                device_token={
                    "user_id": user_id,
                    "platform": platform.value,
                    "action": "updated",
                }
            )
            log.info("Updated device token for user", user_id=user_id)

        return True

    except Exception as e:
        log.error(
            "Failed to register device token",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            device_id=device_id,
        )
        return False


async def get_user_device_count(user_id: str) -> int:
    """Get the number of devices registered for a user."""
    try:
        return await device_token_repository.count_for_user(user_id)
    except Exception as e:
        log.error(
            "Failed to get device count",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return 0


async def verify_token_ownership(token: str, user_id: str) -> bool:
    """Verify that a token belongs to the specified user."""
    try:
        return await device_token_repository.get(token, user_id=user_id) is not None
    except Exception as e:
        log.error(
            "Failed to verify token ownership",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return False


async def unregister_device_token(token: str, user_id: str) -> bool:
    """Unregister a device token, deleting it only if it belongs to the user. Returns success."""
    try:
        if await device_token_repository.delete(token, user_id=user_id):
            log.set(device_token={"user_id": user_id, "action": "unregistered"})
            log.info("Unregistered device token", user_id=user_id)
            return True
        log.warning("Device token not found or not owned by user", user_id=user_id)
        return False

    except Exception as e:
        log.error(
            "Failed to unregister device token",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return False
