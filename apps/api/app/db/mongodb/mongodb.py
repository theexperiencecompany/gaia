import sys
from datetime import timezone
from functools import lru_cache

import pymongo
from app.config.loggers import mongo_logger as logger
from app.config.settings import settings
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.server_api import ServerApi


class MongoDB:
    """
    A class to manage the MongoDB connection using Motor.
    """

    client: AsyncIOMotorClient
    database: AsyncIOMotorDatabase

    def __init__(self, uri: str | None, db_name: str):
        """
        Initialize the MongoDB connection.

        Args:
            uri (str): MongoDB connection string.
            db_name (str): Name of the database.
        """
        if not uri:
            logger.error("MongoDB URI is not found in the environment variables.")
            sys.exit(1)

        try:
            self.client = AsyncIOMotorClient(
                uri, server_api=ServerApi("1"), tz_aware=True, tzinfo=timezone.utc
            )
            self.database = self.client.get_database(db_name)

        except Exception as e:
            logger.error(f"An error occurred while connecting to MongoDB: {e}")
            sys.exit(1)

    def ping(self):
        try:
            # Use the same URI that was used to initialize the async client
            sync_client = pymongo.MongoClient(settings.MONGO_DB)
            sync_client.admin.command("ping")
            sync_client.close()
        except Exception as e:
            logger.error(f"Ping failed: {e}")

    async def _initialize_indexes(self):
        try:
            logger.info("Initializing all indexes in MongoDB...")
            # Import here to avoid circular import
            from app.db.mongodb.indexes import create_all_indexes

            await create_all_indexes()
            # await log_index_summary()
        except Exception as e:
            logger.error(f"Error while initializing indexes: {e}")

    def get_collection(self, collection_name: str):
        return self.database.get_collection(collection_name)


@lru_cache(maxsize=1)
def init_mongodb():
    """
    Initialize MongoDB connection and set it in the app state.

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    logger.info("Initializing MongoDB...")
    mongodb_instance = MongoDB(uri=settings.MONGO_DB, db_name="GAIA")
    logger.info("Created MongoDB instance")
    mongodb_instance.ping()
    logger.info("Successfully connected to MongoDB.")
    return mongodb_instance
