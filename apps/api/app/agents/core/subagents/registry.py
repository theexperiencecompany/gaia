"""Canonical subagent registry.

Single source of truth for "what subagents exist". Combines:
- OAuth integrations whose `subagent_config.has_subagent` is True (adapted
  via `_from_oauth`).
- `BUILTIN_SUBAGENTS` (registered directly, no OAuth).

All subagent code (handoff, registration, ChromaDB indexing, evals, helpers)
goes through `all_subagents()` and `get_subagent_by_id()` here. OAuth
integration code continues to iterate `OAUTH_INTEGRATIONS` directly and
never sees builtins.
"""

from functools import cache

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.oauth_models import OAuthIntegration
from app.models.subagent_models import Subagent

from .builtin_subagents import BUILTIN_SUBAGENTS


def _from_oauth(integ: OAuthIntegration) -> Subagent:
    if integ.subagent_config is None:
        raise ValueError(f"_from_oauth called on integration without subagent_config: {integ.id}")
    return Subagent(
        id=integ.id,
        name=integ.name,
        provider=integ.provider,
        managed_by=integ.managed_by,
        config=integ.subagent_config,
        short_name=integ.short_name,
        mcp_config=integ.mcp_config,
    )


@cache
def all_subagents() -> tuple[Subagent, ...]:
    """All subagents — OAuth-derived + builtins. Process-lifetime cached.

    Cache is safe because `OAUTH_INTEGRATIONS` and `BUILTIN_SUBAGENTS` are
    module-level constants that are never mutated at runtime. If a test
    needs to inject a fake subagent, call `all_subagents.cache_clear()`.
    """
    oauth_subagents = tuple(
        _from_oauth(i)
        for i in OAUTH_INTEGRATIONS
        if i.subagent_config and i.subagent_config.has_subagent
    )
    return oauth_subagents + BUILTIN_SUBAGENTS


def get_subagent_by_id(subagent_id: str) -> Subagent | None:
    """Look up a subagent by `id` or `short_name` (case-insensitive).

    Not cached — takes an arbitrary string and we don't want unbounded
    growth from caller-controlled input. The underlying `all_subagents()`
    is cached, so this is O(n) over a small fixed set.
    """
    s = subagent_id.lower().strip()
    for sa in all_subagents():
        if sa.id.lower() == s or (sa.short_name and sa.short_name.lower() == s):
            return sa
    return None
