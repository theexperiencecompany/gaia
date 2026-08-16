"""The section bodies behind the context table.

Every one of these degrades to ``""`` rather than raising, so the failure path
is the important half: a recall timeout must cost the user a thinner prompt, not
their whole turn. Each also declines to render at all when the context it needs
is absent — that precondition lives with the read rather than at the call site,
so no caller can forget it.
"""

from unittest.mock import AsyncMock, patch

import pytest
from tests._harness.context_sources import knowledge, memory

from app.agents.context.fetchers import (
    build_active_todo_banner,
    build_background_banner,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_tracked_todos_block,
    build_workspace_session_banner,
)
from app.agents.context.section_context import ExecutionMode, SectionContext
from app.agents.context.tiers import AgentTier
from app.models.memory_models import MemorySearchResult
from app.models.todo_models import TodoDocument


def ctx(
    *,
    user_id: str | None = "user1",
    query: str | None = "q",
    active_todo_id: str | None = None,
    execution_mode: ExecutionMode = "interactive",
) -> SectionContext:
    """A comms context carrying everything these sections read, minus overrides."""
    return SectionContext(
        tier=AgentTier.COMMS,
        user_id=user_id,
        query=query,
        active_todo_id=active_todo_id,
        execution_mode=execution_mode,
    )


@pytest.mark.unit
class TestMemoryRecallBlock:
    async def test_renders_every_memory_with_its_date(self) -> None:
        """Dated, not raw: temporal reasoning ("how long ago", "which first")
        has to be answerable from the injected text without another tool call."""
        results = MemorySearchResult(
            memories=[
                memory("User likes coffee", mentioned="2026-01-05"),
                memory("User prefers dark mode", mentioned="2026-02-11"),
            ],
            total_count=2,
        )
        with patch("app.memory.engine.memory_engine.recall", AsyncMock(return_value=results)):
            block = await build_memory_recall_block(ctx(query="coffee"))

        assert "User likes coffee" in block
        assert "[mentioned 2026-01-05]" in block
        assert "User prefers dark mode" in block
        assert "[mentioned 2026-02-11]" in block

    async def test_no_memories_yields_no_block(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.recall",
            AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0)),
        ):
            assert await build_memory_recall_block(ctx()) == ""

    async def test_a_failed_recall_costs_the_block_not_the_turn(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.recall",
            AsyncMock(side_effect=RuntimeError("chroma down")),
        ):
            assert await build_memory_recall_block(ctx()) == ""


@pytest.mark.unit
class TestCoreMemoryBlock:
    async def test_renders_the_core_context(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(return_value="- Ships on Fridays"),
        ):
            block = await build_core_memory_block(ctx())

        assert "Ships on Fridays" in block

    async def test_empty_core_context_yields_no_block(self) -> None:
        with patch("app.memory.engine.memory_engine.get_core_context", AsyncMock(return_value="")):
            assert await build_core_memory_block(ctx()) == ""

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            assert await build_core_memory_block(ctx()) == ""


@pytest.mark.unit
class TestGaiaKnowledgeBlock:
    async def test_renders_each_result(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[knowledge("Gaia can manage calendar")]),
        ):
            block = await build_gaia_knowledge_block(ctx(query="calendar"))

        assert "Gaia can manage calendar" in block

    async def test_no_results_yields_no_block(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[]),
        ):
            assert await build_gaia_knowledge_block(ctx()) == ""

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(side_effect=RuntimeError("chroma fail")),
        ):
            assert await build_gaia_knowledge_block(ctx()) == ""


@pytest.mark.unit
class TestConnectedIntegrationsManifest:
    async def test_one_line_per_integration_with_its_handoff_id(self) -> None:
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[{"id": "gmail", "name": "Gmail"}]),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == "HEADER:\n- Gmail (gmail)"

    async def test_a_name_equal_to_its_id_is_not_rendered_twice(self) -> None:
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[{"id": "notion-mcp", "name": "notion-mcp"}]),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == "HEADER:\n- notion-mcp"

    async def test_no_integrations_yields_no_manifest_not_a_bare_header(self) -> None:
        """A lone header would tell the agent it has a list and that the list is
        empty in a way that reads like a fetch failure."""
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[]),
        ):
            assert await build_connected_integrations_manifest("u1", header="HEADER:") == ""

    async def test_failure_yields_no_manifest(self) -> None:
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_connected_integrations_manifest("u1", header="HEADER:") == ""


@pytest.mark.unit
class TestTrackedTodosBlock:
    async def test_renders_the_cached_summary(self) -> None:
        with patch(
            "app.agents.context.fetchers._cached_tracked_todos_summary",
            AsyncMock(return_value="Tracked: ship the refactor"),
        ):
            assert await build_tracked_todos_block(ctx()) == "Tracked: ship the refactor"

    async def test_a_pinned_view_bypasses_the_cache(self) -> None:
        """Caching the pinned form would surface one run's bound todo on every
        other turn for that user until the TTL expired — the cache key is the
        user alone."""
        cached = AsyncMock(return_value="cached summary")
        with (
            patch("app.agents.context.fetchers._cached_tracked_todos_summary", cached),
            patch(
                "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
                AsyncMock(return_value="pinned summary"),
            ),
        ):
            assert await build_tracked_todos_block(ctx(active_todo_id="todo-7")) == "pinned summary"

        cached.assert_not_awaited()

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.agents.context.fetchers._cached_tracked_todos_summary",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_tracked_todos_block(ctx()) == ""

    async def test_a_pinned_view_failing_yields_no_block(self) -> None:
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_tracked_todos_block(ctx(active_todo_id="todo-7")) == ""


@pytest.mark.unit
class TestWorkspaceSessionBanner:
    async def test_states_both_the_directory_and_the_public_url(self) -> None:
        """The agent needs the directory to write where the watcher scans, and
        the URL base to link what it wrote. Missing either makes it guess."""
        banner = await build_workspace_session_banner(
            SectionContext(tier=AgentTier.EXECUTOR, vfs_session_id="sess-1")
        )

        assert "sess-1" in banner
        assert "Session directory:" in banner
        assert "Public artifact URL:" in banner

    async def test_no_vfs_session_id_never_guesses_a_directory(self) -> None:
        """A fallback to ``thread_id`` would name ``executor_<conv>``, sending
        deliverables outside the directory the artifact watcher scans."""
        banner = await build_workspace_session_banner(
            SectionContext(tier=AgentTier.EXECUTOR, vfs_session_id=None)
        )

        assert banner == ""


@pytest.mark.unit
class TestActiveTodoBanner:
    async def test_names_the_todo_it_binds_the_run_to(self) -> None:
        todo = TodoDocument(id="todo-7", user_id="u1", title="Ship the refactor")
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=todo)):
            banner = await build_active_todo_banner(ctx(active_todo_id="todo-7"))

        assert "todo-7" in banner
        assert "Ship the refactor" in banner

    async def test_a_missing_todo_yields_no_banner(self) -> None:
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=None)):
            assert await build_active_todo_banner(ctx(active_todo_id="gone")) == ""

    async def test_failure_yields_no_banner(self) -> None:
        with patch(
            "app.db.repositories.todos.todo_repository.get",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_active_todo_banner(ctx(active_todo_id="todo-7")) == ""


@pytest.mark.unit
class TestBackgroundBanner:
    async def test_a_background_run_is_told_no_human_is_reading(self) -> None:
        banner = await build_background_banner(ctx(execution_mode="background"))

        assert "BACKGROUND EXECUTION" in banner

    async def test_an_interactive_run_gets_no_banner(self) -> None:
        assert await build_background_banner(ctx()) == ""


@pytest.mark.unit
class TestASectionDeclinesWhenItsContextIsAbsent:
    """The precondition lives with the read, not at the call site, so a section
    registered directly against a fetcher cannot be given a context it needs and
    render a header over nothing."""

    async def test_no_user_means_no_core_memory(self) -> None:
        assert await build_core_memory_block(ctx(user_id=None)) == ""

    @pytest.mark.parametrize("missing", [{"user_id": None}, {"query": None}])
    async def test_recall_needs_both_a_user_and_a_query(self, missing: dict[str, None]) -> None:
        assert await build_memory_recall_block(ctx(**missing)) == ""

    async def test_no_query_means_no_knowledge_lookup(self) -> None:
        assert await build_gaia_knowledge_block(ctx(query=None)) == ""

    async def test_no_user_means_no_tracked_todos(self) -> None:
        assert await build_tracked_todos_block(ctx(user_id=None)) == ""

    @pytest.mark.parametrize("missing", ["user_id", "active_todo_id"])
    async def test_the_active_todo_banner_needs_both_ids(self, missing: str) -> None:
        present: dict[str, str | None] = {"user_id": "user1", "active_todo_id": "todo-7"}
        assert await build_active_todo_banner(ctx(**{**present, missing: None})) == ""
