"""
Device Token Service for Push Notifications
"""

from datetime import datetime, timezone
from typing import List, Optional

from app.config.loggers import notification_logger as logger
from app.db.mongodb.mongodb import MongoDB
from app.models.device_token_models import PlatformType
from motor.motor_asyncio import AsyncIOMotorCollection


class DeviceTokenService:
    """Service for managing device push notification tokens"""

    def __init__(self, mongodb: MongoDB):
        self.collection: AsyncIOMotorCollection = mongodb.database.get_collection(
            "device_tokens"
        )

    async def register_device_token(
        self,
        user_id: str,
        token: str,
        platform: PlatformType,
        device_id: Optional[str] = None,
    ) -> bool:
        """
        Register or update a device token for push notifications

        Args:
            user_id: User ID
            token: Expo push token
            platform: Device platform (ios/android)
            device_id: Optional device identifier

        Returns:
            True if successful, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
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
                logger.info(f"Registered new device token for user {user_id}")
            else:
                logger.info(f"Updated device token for user {user_id}")

            return True

        except Exception as e:
            logger.error(f"Failed to register device token: {e}")
            return False

    async def get_user_device_count(self, user_id: str) -> int:
        """Get the number of devices registered for a user."""
        try:
            return await self.collection.count_documents({"user_id": user_id})
        except Exception as e:
            logger.error(f"Failed to get device count: {e}")
            return 0

    async def verify_token_ownership(self, token: str, user_id: str) -> bool:
        """Verify that a token belongs to the specified user."""
        try:
            doc = await self.collection.find_one({"token": token, "user_id": user_id})
            return doc is not None
        except Exception as e:
            logger.error(f"Failed to verify token ownership: {e}")
            return False

    async def unregister_device_token(self, token: str, user_id: str) -> bool:
        """
        Unregister a device token (mark as inactive or delete)

        Args:
            token: Expo push token to unregister
            user_id: User ID for authorization

        Returns:
            True if successful, False otherwise
        """
        try:
            # Delete only if token belongs to user
            result = await self.collection.delete_one(
                {"token": token, "user_id": user_id}
            )

            # Mask token for logging (show first 20 and last 4 chars)
            masked_token = f"{token[:20]}...{token[-4:]}" if len(token) > 24 else "***"

            if result.deleted_count > 0:
                logger.info(
                    f"Unregistered device token for user {user_id}: {masked_token}"
                )
                return True
            else:
                logger.warning(f"Device token not found or not owned by user {user_id}")
                return False

        except Exception as e:
            logger.error(f"Failed to unregister device token: {e}")
            return False

    async def unregister_user_devices(self, user_id: str) -> int:
        """
        Unregister all device tokens for a user (useful for logout)

        Args:
            user_id: User ID

        Returns:
            Number of tokens unregistered
        """
        try:
            result = await self.collection.delete_many({"user_id": user_id})
            logger.info(
                f"Unregistered {result.deleted_count} devices for user {user_id}"
            )
            return result.deleted_count

        except Exception as e:
            logger.error(f"Failed to unregister user devices: {e}")
            return 0

    async def get_user_tokens(
        self, user_id: str, active_only: bool = True
    ) -> List[str]:
        """
        Get all device tokens for a user

        Args:
            user_id: User ID
            active_only: Return only active tokens

        Returns:
            List of Expo push tokens
        """
        try:
            query: dict = {"user_id": user_id}
            if active_only:
                query["is_active"] = True

            cursor = self.collection.find(query)
            tokens = [doc["token"] async for doc in cursor]

            return tokens

        except Exception as e:
            logger.error(f"Failed to get user tokens: {e}")
            return []

    async def deactivate_invalid_token(self, token: str) -> bool:
        """
        Mark a token as inactive (called when push fails)

        Args:
            token: Expo push token

        Returns:
            True if successful
        """
        try:
            await self.collection.update_one(
                {"token": token},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            masked_token = f"{token[:20]}...{token[-4:]}" if len(token) > 24 else "***"
            logger.info(f"Deactivated invalid token: {masked_token}")
            return True

        except Exception as e:
            logger.error(f"Failed to deactivate token: {e}")
            return False


# Global service instance
device_token_service: Optional[DeviceTokenService] = None


def get_device_token_service() -> DeviceTokenService:
    """Get the global device token service instance"""
    global device_token_service

    if device_token_service is None:
        from app.db.mongodb.mongodb import init_mongodb

        mongodb = init_mongodb()
        device_token_service = DeviceTokenService(mongodb)

    return device_token_service
