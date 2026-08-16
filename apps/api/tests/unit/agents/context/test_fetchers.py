"""The reads behind the context sections.

Every one of these degrades to ``""`` rather than raising, so the failure path
is the important half: a recall timeout must cost the user a thinner prompt, not
their whole turn.
"""

from unittest.mock import AsyncMock, patch

import pytest
from tests._harness.context_sources import knowledge, memory

from app.agents.context.fetchers import (
    build_active_todo_banner,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_workspace_session_banner,
)
from app.models.memory_models import MemorySearchResult
from app.models.todo_models import TodoDocument


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
            block = await build_memory_recall_block("user1", "coffee")

        assert "User likes coffee" in block
        assert "[mentioned 2026-01-05]" in block
        assert "User prefers dark mode" in block
        assert "[mentioned 2026-02-11]" in block

    async def test_no_memories_yields_no_block(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.recall",
            AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0)),
        ):
            assert await build_memory_recall_block("user1", "q") == ""

    async def test_a_failed_recall_costs_the_block_not_the_turn(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.recall",
            AsyncMock(side_effect=RuntimeError("chroma down")),
        ):
            assert await build_memory_recall_block("user1", "q") == ""


@pytest.mark.unit
class TestCoreMemoryBlock:
    async def test_renders_the_core_context(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(return_value="- Ships on Fridays"),
        ):
            block = await build_core_memory_block("user1")

        assert "Ships on Fridays" in block

    async def test_empty_core_context_yields_no_block(self) -> None:
        with patch("app.memory.engine.memory_engine.get_core_context", AsyncMock(return_value="")):
            assert await build_core_memory_block("user1") == ""

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            assert await build_core_memory_block("user1") == ""


@pytest.mark.unit
class TestGaiaKnowledgeBlock:
    async def test_renders_each_result(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[knowledge("Gaia can manage calendar")]),
        ):
            block = await build_gaia_knowledge_block("calendar")

        assert "Gaia can manage calendar" in block

    async def test_no_results_yields_no_block(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[]),
        ):
            assert await build_gaia_knowledge_block("q") == ""

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(side_effect=RuntimeError("chroma fail")),
        ):
            assert await build_gaia_knowledge_block("q") == ""


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
class TestWorkspaceSessionBanner:
    def test_states_both_the_directory_and_the_public_url(self) -> None:
        """The agent needs the directory to write where the watcher scans, and
        the URL base to link what it wrote. Missing either makes it guess."""
        banner = build_workspace_session_banner("sess-1")

        assert "sess-1" in banner
        assert "Session directory:" in banner
        assert "Public artifact URL:" in banner


@pytest.mark.unit
class TestActiveTodoBanner:
    async def test_names_the_todo_it_binds_the_run_to(self) -> None:
        todo = TodoDocument(id="todo-7", user_id="u1", title="Ship the refactor")
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=todo)):
            banner = await build_active_todo_banner("u1", "todo-7")

        assert "todo-7" in banner
        assert "Ship the refactor" in banner

    async def test_a_missing_todo_yields_no_banner(self) -> None:
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=None)):
            assert await build_active_todo_banner("u1", "gone") == ""

    async def test_failure_yields_no_banner(self) -> None:
        with patch(
            "app.db.repositories.todos.todo_repository.get",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_active_todo_banner("u1", "todo-7") == ""
