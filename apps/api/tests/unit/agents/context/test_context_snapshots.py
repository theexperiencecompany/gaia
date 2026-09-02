"""What every tier's model actually sees, recorded line by line.

Scaffolding for the context-assembly refactor, not the deliverable: a snapshot
records whatever the code does, so it cannot fail meaningfully on its own. Its
job is to make a structural change reviewable — every movement in
``__snapshots__/`` must be attributable to a named test in
``test_context_invariants.py`` or ``test_context_defects.py``.
"""

import pytest
from tests._harness.context_chain import (
    FIXED_NOW,
    AgentTier,
    ContextSeed,
    HarnessUser,
    effective_context,
)
from tests._harness.context_snapshot import assert_snapshot
from tests._harness.context_sources import ContextSources, knowledge, memory

from app.models.todo_models import TodoDocument

#: One fixture across all five tiers, so a difference between two snapshots is a
#: difference between the tiers rather than between their inputs.
COMMON_USER = HarnessUser(
    user_id="user-alpha",
    name="Ada",
    email="ada@example.com",
    timezone="Asia/Kolkata",
    preferences={"profession": "engineer"},
)

COMMON_SOURCES = ContextSources(
    core_memory="- Prefers short answers.",
    memories=[memory("Ships on Fridays", mentioned="2026-02-01")],
    gaia_knowledge=[knowledge("GAIA can run scheduled workflows.")],
    tracked_todos="Tracked: ship the context refactor",
    skills="## Available skills\n- inbox-triage",
    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
    provider_metadata={"email": "ada@example.com"},
    custom_instructions="Always archive newsletters.",
    workflow_integrations_hint="# Connected integrations\nGmail (`gmail`)",
)

ACTIVE_TODO = TodoDocument(
    id="todo-7",
    user_id="user-alpha",
    title="Ship the context refactor",
)

BOUND_RUN_SOURCES = ContextSources(
    core_memory=COMMON_SOURCES.core_memory,
    memories=COMMON_SOURCES.memories,
    gaia_knowledge=COMMON_SOURCES.gaia_knowledge,
    tracked_todos=COMMON_SOURCES.tracked_todos,
    skills=COMMON_SOURCES.skills,
    connected_integrations=COMMON_SOURCES.connected_integrations,
    provider_metadata=COMMON_SOURCES.provider_metadata,
    custom_instructions=COMMON_SOURCES.custom_instructions,
    active_todo=ACTIVE_TODO,
)

QUERY = "summarise my unread mail"


@pytest.mark.unit
class TestTierSnapshots:
    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_common_fixture(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier, ContextSeed(user=COMMON_USER, query=QUERY, sources=COMMON_SOURCES)
        )
        assert_snapshot(f"tier_{tier.value}", messages)

    @pytest.mark.parametrize("tier", [AgentTier.EXECUTOR, AgentTier.PROVIDER_SUBAGENT])
    async def test_bound_background_run_shows_both_banners(self, tier: AgentTier) -> None:
        """An active todo plus a headless run — the only shape where both
        run-binding banners appear at once."""
        messages = await effective_context(
            tier,
            ContextSeed(
                user=COMMON_USER,
                query=QUERY,
                sources=BOUND_RUN_SOURCES,
                configurable_overrides={
                    "active_todo_id": ACTIVE_TODO.id,
                    "execution_mode": "background",
                },
            ),
        )
        assert_snapshot(f"bound_background_{tier.value}", messages)

    async def test_multi_turn_thread_collapses_stale_slots(self) -> None:
        """A checkpointed thread carrying a stale copy of every slot. Pins the
        'exactly one per slot, and it is the latest' behaviour end to end."""
        stale = await effective_context(
            AgentTier.EXECUTOR,
            ContextSeed(
                user=COMMON_USER,
                query="an older question",
                sources=COMMON_SOURCES,
                now=FIXED_NOW.replace(hour=9),
            ),
        )
        messages = await effective_context(
            AgentTier.EXECUTOR,
            ContextSeed(
                user=COMMON_USER, query=QUERY, sources=COMMON_SOURCES, prior_messages=stale
            ),
        )
        assert_snapshot("multi_turn_executor", messages)
