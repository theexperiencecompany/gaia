"""
MongoDB Collections with Lazy Loading.

This module provides access to MongoDB collections using lazy initialization
to optimize application startup performance.

Implementation:
    - Collections are created on-demand when first accessed
    - MongoDB connections are deferred until actual database operations
    - Uses Python's __getattr__ for transparent lazy loading
    - Maintains backward compatibility with existing import syntax

Usage:
    from app.db.mongodb.collections import blog_collection

    # Import is instant - no database connection yet
    result = await blog_collection.find_one({"_id": id})  # Connection happens here

Performance:
    - Import time: ~0.001s (previously ~1+ seconds)
    - Memory: Only initializes collections that are actually used
    - Runtime: First access initializes, subsequent access is cached
"""

import pymongo
from app.config.loggers import app_logger as logger  # Cache for lazy-loaded collections
from pymongo.server_api import ServerApi

# Cache for async (Motor) collections
_collections_cache = {}
_mongodb_instance = None

# Cache for sync (PyMongo) collections
_sync_collections_cache = {}
_sync_client = None
_sync_db = None


def _get_mongodb_instance():
    """Get or create async MongoDB instance (Motor)."""
    global _mongodb_instance
    if _mongodb_instance is None:
        logger.info("Initializing MongoDB instance (lazy loading)")
        from app.db.mongodb.mongodb import init_mongodb

        _mongodb_instance = init_mongodb()
        logger.info("MongoDB instance initialized")
    return _mongodb_instance


def _get_collection(collection_name: str):
    """Get async collection with lazy loading and caching."""
    if collection_name not in _collections_cache:
        logger.info(f"Creating async collection '{collection_name}' (lazy loading)")
        mongodb_instance = _get_mongodb_instance()
        _collections_cache[collection_name] = mongodb_instance.get_collection(
            collection_name
        )
    return _collections_cache[collection_name]


def _get_sync_db():
    """Get or create sync PyMongo client and database."""
    global _sync_client, _sync_db
    if _sync_db is None:
        from app.config.settings import settings

        logger.info("Initializing sync MongoDB client (PyMongo)")
        _sync_client = pymongo.MongoClient(settings.MONGO_DB, server_api=ServerApi("1"))
        _sync_db = _sync_client.get_database("GAIA")
        logger.info("Sync MongoDB client initialized")
    return _sync_db


def get_sync_collection(collection_name: str):
    """
    Get a synchronous PyMongo collection for use in sync code.

    This is useful for sync functions that need to access MongoDB
    without using asyncio (e.g., Composio tools, sync services).

    Args:
        collection_name: The name of the MongoDB collection

    Returns:
        A PyMongo Collection object (sync)
    """
    if collection_name not in _sync_collections_cache:
        logger.info(f"Creating sync collection '{collection_name}' (lazy loading)")
        db = _get_sync_db()
        _sync_collections_cache[collection_name] = db.get_collection(collection_name)
    return _sync_collections_cache[collection_name]


# Collection name mappings
_COLLECTION_MAPPINGS = {
    "users_collection": "users",
    "conversations_collection": "conversations",
    "goals_collection": "goals",
    "notes_collection": "notes",
    "calendars_collection": "calendar",
    "feedback_collection": "feedback_form",
    "waitlist_collection": "waitlist",
    "mail_collection": "mail",
    "blog_collection": "blog",
    "team_collection": "team",
    "search_urls_collection": "search_urls",
    "files_collection": "files",
    "notifications_collection": "notifications",
    "todos_collection": "todos",
    "projects_collection": "projects",
    "reminders_collection": "reminders",
    "workflows_collection": "workflows",
    "support_collection": "support_requests",
    "payments_collection": "payments",
    "subscriptions_collection": "subscriptions",
    "plans_collection": "subscription_plans",
    "usage_snapshots_collection": "usage_snapshots",
    "ai_models_collection": "ai_models",
    "integrations_collection": "integrations",
    "user_integrations_collection": "user_integrations",
    "device_tokens_collection": "device_tokens",
    "vfs_nodes_collection": "vfs_nodes",
}


def __getattr__(name: str):
    """
    Lazy loading of collections using module-level __getattr__.

    This is called when someone tries to import a collection that doesn't exist
    as a module-level variable. We create it on-demand.
    """
    if name in _COLLECTION_MAPPINGS:
        collection_name = _COLLECTION_MAPPINGS[name]
        return _get_collection(collection_name)

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
