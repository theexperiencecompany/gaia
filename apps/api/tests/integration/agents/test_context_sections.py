"""The two context sections with real behaviour behind them, un-mocked.

The unit tier fakes every section's read, which is what makes those tests fast
and deterministic — and also what makes them blind to the fake drifting from the
real service. These two sections have the most logic between the store and the
rendered text (a status filter plus a name resolution; a pin, a sort and a
relative-time render), so they are where a fake is most likely to be wrong while
staying green.

Real production code from the section down; mocked only at the repository and
catalog seams, one layer below the behaviour under test.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.context.section_context import SectionContext
from app.agents.context.sections import SECTIONS, Section
from app.agents.context.slots import PromptSlot
from app.agents.context.text import EXECUTOR_CONNECTED_INTEGRATIONS_HEADER
from app.agents.context.tiers import AgentTier
from app.models.todo_models import TodoDocument


@pytest.fixture
def user() -> str:
    """A user nobody has cached anything for.

    Both sections under test sit behind a per-user cache — the manifest under
    ``@Cacheable``, the todo summary under its own Redis key — and these tests
    mock the store one layer BELOW that. A fixed id would make the result
    depend on whatever Redis happened to be holding, which is how this file
    passed once and then failed against the same code.
    """
    return f"user-ctx-{uuid4()}"


def _ctx(user_id: str) -> SectionContext:
    return SectionContext(tier=AgentTier.EXECUTOR, user_id=user_id)


def _section(section_id: str) -> Section:
    return next(s for s in SECTIONS if s.id == section_id)


@pytest.mark.integration
class TestConnectedIntegrationsManifest:
    """Runs the real ``get_connected_integrations_named`` — the status filter and
    the custom-MCP name resolution — over mocked integration records."""

    @staticmethod
    def _records(*records: dict[str, str]):
        return patch(
            "app.services.integrations.user_integrations.get_user_integration_records",
            AsyncMock(return_value=list(records)),
        )

    async def test_only_connected_integrations_reach_the_agent(self, user: str) -> None:
        """A disconnected integration listed as available is worse than absent:
        the executor hands off to it and the handoff fails."""
        with self._records(
            {"integration_id": "gmail", "status": "connected"},
            {"integration_id": "slack", "status": "disconnected"},
            {"integration_id": "notion", "status": "pending"},
        ):
            block = await _section("integrations_manifest").fetch(_ctx(user))

        assert "gmail" in block
        assert "slack" not in block
        assert "notion" not in block

    async def test_the_executor_gets_the_handoff_framed_header(self, user: str) -> None:
        with self._records({"integration_id": "gmail", "status": "connected"}):
            block = await _section("integrations_manifest").fetch(_ctx(user))

        assert block.startswith(EXECUTOR_CONNECTED_INTEGRATIONS_HEADER)

    async def test_comms_gets_the_capability_framed_header_instead(self, user: str) -> None:
        with self._records({"integration_id": "gmail", "status": "connected"}):
            block = await _section("integrations_manifest").fetch(
                SectionContext(tier=AgentTier.COMMS, user_id=user)
            )

        assert not block.startswith(EXECUTOR_CONNECTED_INTEGRATIONS_HEADER)
        assert "gmail" in block

    async def test_no_connected_integrations_yields_nothing_at_all(self, user: str) -> None:
        with self._records({"integration_id": "gmail", "status": "disconnected"}):
            assert await _section("integrations_manifest").fetch(_ctx(user)) == ""

    async def test_the_manifest_is_a_stable_section(self) -> None:
        """It changes on connect/disconnect, never per turn — so it belongs in
        the cacheable prefix, and a reclassification must be deliberate."""
        assert _section("integrations_manifest").slot is PromptSlot.DYNAMIC_STABLE


@pytest.mark.integration
class TestTrackedTodosSummary:
    """Runs the real ``get_active_tracked_summary`` — the pin, the ordering and
    the line rendering — over mocked todo documents."""

    @staticmethod
    def _todos(*docs: TodoDocument):
        return patch(
            "app.db.repositories.todos.todo_repository.list_active_tracked",
            AsyncMock(return_value=list(docs)),
        )

    @staticmethod
    def _todo(todo_id: str, title: str, user_id: str) -> TodoDocument:
        return TodoDocument(
            id=todo_id,
            user_id=user_id,
            title=title,
            created_at=datetime.now(UTC) - timedelta(days=1),
        )

    async def test_every_active_todo_is_listed(self, user: str) -> None:
        with self._todos(
            self._todo("t1", "Ship the refactor", user), self._todo("t2", "Review the PR", user)
        ):
            block = await _section("tracked_todos").fetch(
                SectionContext(tier=AgentTier.COMMS, user_id=user)
            )

        assert "Ship the refactor" in block
        assert "Review the PR" in block

    async def test_the_bound_todo_is_pinned_to_the_top(self, user: str) -> None:
        """The run is bound to it, so it has to be the one the agent sees first
        — otherwise the canvas write-target directive names a todo buried in a
        list of fifteen."""
        with self._todos(
            self._todo("t1", "Unrelated work", user), self._todo("t2", "The bound one", user)
        ):
            block = await _section("tracked_todos").fetch(
                SectionContext(tier=AgentTier.COMMS, user_id=user, active_todo_id="t2")
            )

        assert block.index("The bound one") < block.index("Unrelated work")

    async def test_no_active_todos_yields_nothing(self, user: str) -> None:
        with self._todos():
            block = await _section("tracked_todos").fetch(
                SectionContext(tier=AgentTier.COMMS, user_id=user)
            )

        assert block == ""

    async def test_a_pinned_view_bypasses_the_cache(self, user: str) -> None:
        """The pin is per-run-binding, but the cache is keyed by user alone —
        so serving a pinned view from it would show one run's bound todo on
        every other turn for that user until the TTL expired."""
        cached = AsyncMock(return_value="STALE SUMMARY")

        with (
            self._todos(self._todo("t1", "Fresh todo", user)),
            patch("app.agents.context.fetchers._cached_tracked_todos_summary", cached),
        ):
            pinned = await _section("tracked_todos").fetch(
                SectionContext(tier=AgentTier.COMMS, user_id=user, active_todo_id="t1")
            )

        assert "Fresh todo" in pinned
        assert "STALE SUMMARY" not in pinned
        cached.assert_not_awaited()

    async def test_the_summary_is_a_volatile_section(self) -> None:
        """It changes as the agent works, so it must not sit in the prefix."""
        assert _section("tracked_todos").slot is PromptSlot.MEMORY_RECALL
