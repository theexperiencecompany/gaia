"""Typed, cache-integrated repository layer — the only path to MongoDB.

See ``CLAUDE.md`` in this directory for the rules and the three type-safety
layers that keep the boundary clean.
"""

from app.db.repositories.base import (
    MongoDocument,
    MongoRepository,
    UserScopedDocument,
    UserScopedRepository,
    cached_query,
)
from app.db.repositories.cache import CachePolicy

__all__ = [
    "CachePolicy",
    "MongoDocument",
    "MongoRepository",
    "UserScopedDocument",
    "UserScopedRepository",
    "cached_query",
]
