"""Typed, cache-integrated repository layer — the only path to MongoDB.

See CLAUDE.md in this directory for the rules and the three type-safety
layers that keep the boundary clean.
"""

from app.db.repositories.base import (
    MongoDocument,
    MongoRepository,
    UserScopedDocument,
    UserScopedRepository,
)
from app.db.repositories.cache import CachePolicy
from app.db.repositories.cached_base import (
    CachedMongoRepository,
    CachedUserScopedRepository,
    cached_query,
)

__all__ = [
    "CachePolicy",
    "CachedMongoRepository",
    "CachedUserScopedRepository",
    "MongoDocument",
    "MongoRepository",
    "UserScopedDocument",
    "UserScopedRepository",
    "cached_query",
]
