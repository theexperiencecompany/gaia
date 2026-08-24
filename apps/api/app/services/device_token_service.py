"""
Device Token Service for Push Notifications
"""

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.mongodb.mongodb import MongoDB
from app.models.device_token_models import PlatformType
from shared.py.wide_events import log


class DeviceTokenService:
    """Service for managing device push notification tokens"""

    def __init__(self, mongodb: MongoDB):
        self.collection: AsyncIOMotorCollection = mongodb.database.get_collection("device_tokens")

    async def register_device_token(
        self,
        user_id: str,
        token: str,
        platform: PlatformType,
        device_id: str | None = None,
    ) -> bool:
        """Register or update a device token for push notifications. Returns success."""
        try:
            now = datetime.now(UTC)
            # Use upsert to avoid race condition
            result = await self.collection.update_one(
                {"token": token},
                {
                    "$set": {
                        "user_id": user_id,
                        "platform": platform.value,
                        "device_id": device_id,
                        "is_active": True,
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            if result.upserted_id:
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

    async def get_user_device_count(self, user_id: str) -> int:
        """Get the number of devices registered for a user."""
        try:
            return await self.collection.count_documents({"user_id": user_id})
        except Exception as e:
            log.error(
                "Failed to get device count",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return 0

    async def get_active_tokens(self, user_id: str) -> list[str]:
        """Every active push token registered for this user."""
        # {"token": 1} is a MongoDB field projection (include the token field), not a secret.
        projection = {"token": 1}  # nosec B105
        cursor = self.collection.find({"user_id": user_id, "is_active": True}, projection)
        return [doc["token"] async for doc in cursor if doc.get("token")]

    async def deactivate_tokens(self, tokens: list[str]) -> None:
        """Mark dead tokens inactive so ``get_active_tokens`` stops returning them."""
        if not tokens:
            return
        await self.collection.update_many(
            {"token": {"$in": tokens}}, {"$set": {"is_active": False}}
        )

    async def verify_token_ownership(self, token: str, user_id: str) -> bool:
        """Verify that a token belongs to the specified user."""
        try:
            doc = await self.collection.find_one({"token": token, "user_id": user_id})
            return doc is not None
        except Exception as e:
            log.error(
                "Failed to verify token ownership",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return False

    async def unregister_device_token(self, token: str, user_id: str) -> bool:
        """Unregister a device token, deleting it only if it belongs to the user. Returns success."""
        try:
            # Delete only if token belongs to user
            result = await self.collection.delete_one({"token": token, "user_id": user_id})

            if result.deleted_count > 0:
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


# Global service instance
device_token_service: DeviceTokenService | None = None


def get_device_token_service() -> DeviceTokenService:
    """Get the global device token service instance"""
    global device_token_service

    if device_token_service is None:
        # Deferred import: kept inside the lazy singleton so MongoDB connects on first service access
        from app.db.mongodb.mongodb import init_mongodb  # noqa: PLC0415 -- lazy init

        mongodb = init_mongodb()
        device_token_service = DeviceTokenService(mongodb)

    return device_token_service
