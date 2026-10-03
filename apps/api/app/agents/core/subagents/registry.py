"""Canonical integration manifest (historically the "subagent registry").

Single source of truth for "what integrations exist". Combines OAuth
integrations whose subagent_config.has_subagent is True (adapted via _from_oauth)
and BUILTIN_SUBAGENTS (registered directly, no OAuth).

Integrations activate in-context via activate_integration (only per-user MCP
integrations still run as subagent graphs); the manifest backs activation,
tool-space mapping, connect cards, and skill targets, all through all_subagents()
and get_subagent_by_id(). OAuth integration code continues to iterate
OAUTH_INTEGRATIONS directly and never sees builtins.
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

    Cache is safe because OAUTH_INTEGRATIONS and BUILTIN_SUBAGENTS are
    module-level constants that are never mutated at runtime. If a test
    needs to inject a fake subagent, call all_subagents.cache_clear().
    """
    oauth_subagents = tuple(
        _from_oauth(i)
        for i in OAUTH_INTEGRATIONS
        if i.subagent_config and i.subagent_config.has_subagent
    )
    return oauth_subagents + BUILTIN_SUBAGENTS


def get_subagent_by_id(subagent_id: str) -> Subagent | None:
    """Look up a subagent by id or short_name (case-insensitive).

    Not cached — takes an arbitrary string and we don't want unbounded
    growth from caller-controlled input. The underlying all_subagents()
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

    Internal subagents and short_name are excluded: "todos", "skills", and Google
    Tasks' "tasks" are ordinary words that appear in task prose constantly. Cached
    with all_subagents(); clear both together if a test injects a fake subagent.
    """
    matchers: list[tuple[Subagent, re.Pattern[str]]] = []
    for sa in all_subagents():
        if sa.managed_by == "internal":
            continue
        # Sorted only so the compiled pattern is stable across runs (set order is
        # not); alternation order cannot change whether it matches, and the only
        # consumer reads pattern.search(text) as a boolean, never the matched text.
        alternation = "|".join(re.escape(label) for label in sorted({sa.name, sa.id}))
        matchers.append((sa, re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE)))
    return tuple(matchers)


# Provider ids that are also ordinary English words: a lowercase occurrence reads
# as prose, a capitalized one as the product, so foreign_provider_named_in flags
# these only on a capitalized mention. Every other provider flags on any match.
_COMMON_WORD_PROVIDER_IDS: frozenset[str] = frozenset({"slack", "linear", "notion"})


def providers_named_in(text: str) -> list[Subagent]:
    """Every third-party provider text names, in manifest order.

    Ids in _COMMON_WORD_PROVIDER_IDS count only when capitalized, since their
    lowercase form reads as ordinary prose.
    """
    named: list[Subagent] = []
    for sa, pattern in _third_party_name_matchers():
        match = pattern.search(text)
        if match is None:
            continue
        if sa.id in _COMMON_WORD_PROVIDER_IDS and match.group(0).islower():
            continue
        named.append(sa)
    return named


def foreign_provider_named_in(text: str, target_id: str) -> Subagent | None:
    """Return the third-party provider text names that is not target_id, if any.

    A task routed to one subagent while naming another credits the named product
    with work it never did (eight GAIA todos once reached the user as "8 tasks
    created (Todoist)"). Ids in _COMMON_WORD_PROVIDER_IDS flag only when capitalized.
    """
    return next((sa for sa in providers_named_in(text) if sa.id != target_id), None)


@cache
def _subagent_id_by_agent_name() -> dict[str, str]:
    """Map each subagent's agent_name to its canonical id.

    agent_name is the one handle the skill catalog is keyed on. Built from
    all_subagents(), covering OAuth-derived AND builtin subagents; it is
    also the LangGraph graph-registration key, so it is unique by construction.
    """
    return {sa.config.agent_name: sa.id for sa in all_subagents()}


def resolve_subagent_id(agent_name: str) -> str | None:
    """Resolve a subagent agent_name to its canonical id, or None if unregistered.

    None is the correct answer for the general executor bucket and for
    custom/public MCP subagents that aren't in the registry.
    """
    return _subagent_id_by_agent_name().get(agent_name.strip())
