"""Typed, cache-integrated repository layer — the only path to MongoDB.

See CLAUDE.md in this directory for the rules and the three type-safety
layers that keep the boundary clean.
"""

from app.db.repositories.base import (
    MongoRepository,
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
    "MongoRepository",
    "UserScopedRepository",
    "cached_query",
]
