"""
MongoDB collection access, lazily initialized.

``get_async_collection`` is the single supported way to reach a Motor
collection. The per-collection module attributes it replaced (``users_collection``
and friends) are gone: every domain is behind a typed repository in
``app.db.repositories``, and application code goes through those, never through a
raw handle. The repository layer resolves its own handle here; the boundary lint
in ``tools/lints/repository_boundaries.py`` keeps it that way.

Usage:
    from app.db.mongodb.collections import get_async_collection

    # Import is instant — the connection is opened on first resolution.
    collection = get_async_collection("blog")

Collections are created on demand and cached, so the MongoDB connection is
deferred until a collection is actually used rather than paid at import time.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.constants.log_tags import LogTag
from app.db.mongodb.mongodb import MongoDB
from shared.py.wide_events import log

# Cache for async (Motor) collections
_collections_cache: dict[str, AsyncIOMotorCollection[dict[str, Any]]] = {}
_mongodb_instance: MongoDB | None = None


def _get_mongodb_instance() -> MongoDB:
    """Get or create async MongoDB instance (Motor)."""
    global _mongodb_instance
    if _mongodb_instance is None:
        log.info(f"{LogTag.MONGO} Initializing MongoDB instance (lazy loading)")
        # Deferred import: kept inside the lazy initializer so MongoDB connects on first collection access, not at import
        from app.db.mongodb.mongodb import init_mongodb  # noqa: PLC0415 -- lazy init

        _mongodb_instance = init_mongodb()
        log.info(f"{LogTag.MONGO} MongoDB instance initialized")
    return _mongodb_instance


def _get_collection(collection_name: str) -> AsyncIOMotorCollection[dict[str, Any]]:
    """Get async collection with lazy loading and caching."""
    if collection_name not in _collections_cache:
        log.info(
            f"{LogTag.MONGO} Creating async collection (lazy loading)",
            collection_name=collection_name,
        )
        mongodb_instance = _get_mongodb_instance()
        _collections_cache[collection_name] = mongodb_instance.get_collection(collection_name)
    return _collections_cache[collection_name]


def get_async_collection(collection_name: str) -> AsyncIOMotorCollection[dict[str, Any]]:
    """Resolve a Motor collection by its Mongo name — the only collection accessor.

    Repositories declare a ``collection_name`` and resolve their handle through
    this one function. Application code outside ``app/db/`` calls a repository,
    not this.
    """
    return _get_collection(collection_name)
