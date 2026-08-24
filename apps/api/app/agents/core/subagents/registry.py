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
import re

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


@cache
def _third_party_name_matchers() -> tuple[tuple[Subagent, re.Pattern[str]], ...]:
    """One whole-word matcher per third-party provider, over its name and its id.

    Internal subagents are deliberately absent as *matches*: "todos",
    "reminders" and "skills" are ordinary words that appear in task prose
    constantly, and a generic noun cannot mislead anyone about which product
    holds their data. `short_name` is excluded for the same reason — Google
    Tasks' short name is literally "tasks".

    Cached with `all_subagents()`; call `_third_party_name_matchers.cache_clear()`
    alongside it if a test injects a fake subagent.
    """
    matchers: list[tuple[Subagent, re.Pattern[str]]] = []
    for sa in all_subagents():
        if sa.managed_by == "internal":
            continue
        # Sorted only so the compiled pattern is stable across runs (set order
        # is not). Alternation ORDER cannot change whether the pattern matches:
        # the engine backtracks to the next alternative when a boundary lookaround
        # fails, and the only consumer reads `pattern.search(text)` as a boolean,
        # never the matched text.
        alternation = "|".join(re.escape(label) for label in sorted({sa.name, sa.id}))
        matchers.append((sa, re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE)))
    return tuple(matchers)


def foreign_provider_named_in(text: str, target_id: str) -> Subagent | None:
    """The third-party provider ``text`` names that is not ``target_id``, if any.

    A task routed to one subagent while naming another produces a result that
    credits the named product with work it never did — the reason eight GAIA
    todos reached the user as "8 tasks created (Todoist)".
    """
    for sa, pattern in _third_party_name_matchers():
        if sa.id != target_id and pattern.search(text):
            return sa
    return None


@cache
def _subagent_id_by_agent_name() -> dict[str, str]:
    """Map each subagent's `agent_name` to its canonical `id`.

    `agent_name` is the one handle the skill catalog is keyed on: a skill's
    frontmatter `target` is the owning subagent's `agent_name`, and the handoff
    path passes that same `agent_name` when surfacing a subagent's skills. Built
    from `all_subagents()`, so it is the authoritative `agent_name -> id` table
    covering OAuth-derived AND builtin subagents. (`agent_name` is also the
    LangGraph graph-registration key, so it is unique by construction.)
    """
    return {sa.config.agent_name: sa.id for sa in all_subagents()}


def resolve_subagent_id(agent_name: str) -> str | None:
    """Resolve a subagent `agent_name` to its canonical `id`, or `None` if no
    registered subagent uses that `agent_name`.

    `None` is the correct answer for the general `executor` bucket and for
    custom/public MCP subagents that aren't in the registry.
    """
    return _subagent_id_by_agent_name().get(agent_name.strip())
