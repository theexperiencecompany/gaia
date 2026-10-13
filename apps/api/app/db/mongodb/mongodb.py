from datetime import UTC
from functools import lru_cache
import os
import sys
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
import pymongo
from pymongo.server_api import ServerApi

from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# The app always uses this database name regardless of what `MONGO_DB`'s URL names.
# MONGO_DB_NAME overrides it so several CI lanes can share one mongod. Unset = "GAIA".
MONGO_DATABASE_NAME = os.getenv("MONGO_DB_NAME", "GAIA")


class MongoDB:
    """A class to manage the MongoDB connection using Motor."""

    client: AsyncIOMotorClient[dict[str, Any]]
    database: AsyncIOMotorDatabase[dict[str, Any]]

    def __init__(self, uri: str | None, db_name: str):
        if not uri:
            log.error(f"{LogTag.MONGO} MongoDB URI is not found in the environment variables.")
            sys.exit(1)

        try:
            # Cap the pool below Motor's default maxPoolSize=100 to bound memory under load.
            self.client = AsyncIOMotorClient(
                uri,
                server_api=ServerApi("1"),
                tz_aware=True,
                tzinfo=UTC,
                maxPoolSize=20,
                minPoolSize=0,
            )
            self.database = self.client.get_database(db_name)
            log.set(db={"connection_status": "connected", "backend": "mongodb"})

        except Exception as e:
            log.set(db={"connection_status": "error", "backend": "mongodb"})
            log.error(
                f"{LogTag.MONGO} An error occurred while connecting to MongoDB",
                error=str(e),
                error_type=type(e).__name__,
            )
            sys.exit(1)

    def ping(self) -> None:
        """Verify connectivity at startup over a throwaway synchronous client.

        Synchronous on purpose: this runs during startup before an event loop
        owns the Motor client, so it must not borrow one. Failure is logged, not
        raised — reachability is reported, and the lazy providers that actually
        need Mongo fail on their own terms.
        """
        try:
            # Use the same URI that was used to initialize the async client
            sync_client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(
                settings.MONGO_DB
            )
            sync_client.admin.command("ping")
            sync_client.close()
        except Exception as e:
            log.error(f"{LogTag.MONGO} Ping failed", error=str(e), error_type=type(e).__name__)

    async def _initialize_indexes(self) -> None:
        try:
            log.info(f"{LogTag.MONGO} Initializing all indexes in MongoDB...")
            # Import here to avoid circular import
            # Deferred import: breaks circular dependency: indexes imports collections, which imports this module
            from app.db.mongodb.indexes import create_all_indexes  # noqa: PLC0415 -- deferred

            await create_all_indexes()
            # await log_index_summary()
        except Exception as e:
            log.error(
                f"{LogTag.MONGO} Error while initializing indexes",
                error=str(e),
                error_type=type(e).__name__,
            )

    def get_collection(self, collection_name: str) -> AsyncIOMotorCollection[dict[str, Any]]:
        """Return a Motor handle for one collection of the app's database."""
        return self.database.get_collection(collection_name)


@lru_cache(maxsize=1)
def init_mongodb() -> MongoDB:
    """Initialize the MongoDB connection and verify connectivity via a startup ping."""
    log.info(f"{LogTag.MONGO} Initializing MongoDB...")
    mongodb_instance = MongoDB(uri=settings.MONGO_DB, db_name=MONGO_DATABASE_NAME)
    log.info(f"{LogTag.MONGO} Created MongoDB instance")
    mongodb_instance.ping()
    log.info(f"{LogTag.MONGO} Successfully connected to MongoDB.")
    return mongodb_instance


def object_id_filter(id_value: str) -> dict[str, ObjectId]:
    """Build the _id filter for a 24-hex string id, so operational scripts never import bson."""
    return {"_id": ObjectId(id_value)}
