"""JuiceFS shard routing.

Phase 1: single shard, `shard_for()` always returns 0.
Phase 2: hash-based routing across N shards. The Mongo `e2b_sandboxes` doc
records the shard so we never re-shard a user without an explicit migration.
"""

from __future__ import annotations

import hashlib

from app.config.settings import settings


def shard_for(user_id: str) -> int:
    """Return the shard index for a user. Stable for the user's lifetime."""
    # settings is Any (app.config.settings.get_settings() is untyped upstream);
    # JUICEFS_NUM_SHARDS is genuinely int on both Settings subclasses.
    n: int = max(1, settings.JUICEFS_NUM_SHARDS)
    if n == 1:
        return 0
    digest = hashlib.sha256(user_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % n


def shard_meta_url(shard_id: int) -> str:
    """Resolve the JuiceFS metadata URL for the given shard.

    The template in settings contains `{shard}` which is substituted. Single-
    shard deployments may use a template with no `{shard}` placeholder.

    Redis meta uses the DB number as the shard (redis://host:6379/{shard}).
    For Postgres, JuiceFS expects scheme `postgres://`, not `postgresql://` —
    managed providers (Neon, Supabase, etc.) hand out the latter, so we
    rewrite at the boundary.
    """
    template = settings.JUICEFS_META_URL_TEMPLATE or ""
    if "{shard}" in template:
        template = template.replace("{shard}", str(shard_id))
    if template.startswith("postgresql://"):
        template = "postgres://" + template[len("postgresql://") :]
    return template
