"""Generation-based cache policy for the repository layer.

Each cache-enabled repository declares a ``CachePolicy``. Three key families per
scope (``user_id`` for user-scoped repos, else ``"global"``):

    {prefix}:{scope}:{id}            entity cache
    {prefix}:{scope}:gen             generation counter (Redis INCR)
    {prefix}:{scope}:q:{gen}:{hash}  query cache, keyed under the current generation

Every write bumps the generation, which orphans all query caches for that scope
at once — they still carry the old generation in their key. No pattern scans, no
manual invalidation. Redis being down degrades to "skip the cache" (a ``None``
generation), never "serve stale". Serialization rides the existing ``model=``
TypeAdapter path in ``app/db/redis.py`` — no second serializer.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from app.constants.cache import REPO_ENTITY_TTL, REPO_QUERY_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log


@dataclass(frozen=True)
class CachePolicy:
    """Prefix + TTLs for one repository's three cache key families."""

    prefix: str
    entity_ttl: int = REPO_ENTITY_TTL
    query_ttl: int = REPO_QUERY_TTL

    def entity_key(self, scope: str, doc_id: str) -> str:
        return f"{self.prefix}:{scope}:{doc_id}"

    def generation_key(self, scope: str) -> str:
        return f"{self.prefix}:{scope}:gen"

    def query_key(self, scope: str, generation: int, method: str, arg_hash: str) -> str:
        return f"{self.prefix}:{scope}:q:{generation}:{method}:{arg_hash}"


def query_arg_hash(arguments: dict[str, object]) -> str:
    """Stable short hash of a finder's bound arguments (order-independent)."""
    payload = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def read_generation(policy: CachePolicy, scope: str) -> int | None:
    """Current generation for a scope.

    ``None`` means Redis is unavailable — skip the query cache, never serve stale.
    A missing key is generation ``0`` (Redis is up, just no writes yet), distinct
    from ``None`` so a never-written scope still caches instead of skipping forever.
    """
    client = redis_cache.redis
    if client is None:
        return None
    try:
        raw = await client.get(policy.generation_key(scope))
    except Exception as exc:  # Redis hiccup → degrade to no query cache, not an error
        log.warning(f"{LogTag.STORAGE} repo generation read failed for {scope}: {exc}")
        return None
    return int(raw) if raw is not None else 0


async def bump_generation(policy: CachePolicy, scope: str) -> None:
    """INCR the scope's generation, orphaning every query cache under it."""
    client = redis_cache.redis
    if client is None:
        return
    try:
        await client.incr(policy.generation_key(scope))
    except Exception as exc:
        log.warning(f"{LogTag.STORAGE} repo generation bump failed for {scope}: {exc}")
