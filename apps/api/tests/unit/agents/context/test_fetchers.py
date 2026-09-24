"""The section bodies behind the context table.

Every one of these degrades to "" rather than raising, so the failure path
is the important half: a recall timeout must cost the user a thinner prompt, not
their whole turn. Each also declines to render at all when the context it needs
is absent — that precondition lives with the read rather than at the call site,
so no caller can forget it.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests._harness.context_sources import knowledge, memory
from tests.helpers import captured_wide_event

from app.agents.context import fetchers
from app.agents.context.fetchers import (
    NEW_USER_CONVERSATION_LIMIT,
    _dedupe_by_provider,
    _split_core_context,
    _split_off_section,
    build_active_todo_banner,
    build_agenda_and_activity_block,
    build_background_banner,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_new_user_guidance_block,
    build_open_pendings_block,
    build_tracked_todos_block,
    build_workspace_session_banner,
    format_active_todo_banner,
)
from app.agents.context.section_context import ExecutionMode, SectionContext
from app.agents.context.text import (
    CORE_MEMORY_HEADER,
    GAIA_KNOWLEDGE_HEADER,
    MEMORY_IS_PAST_NOTE,
    MEMORY_RECALL_HEADER,
)
from app.agents.context.tiers import AgentTier
from app.agents.prompts.new_user_prompts import (
    NEED_PLAYBOOKS,
    NEW_USER_GUIDANCE_TEMPLATE,
    SEEDED_CHIPS_RULE,
    TARGET_REPLY_EXAMPLE,
    build_new_user_guidance,
)
from app.agents.workspace.paths import session_dir
from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.models.memory_models import MemorySearchResult
from app.models.todo_models import TodoDocument
from app.models.user_models import NEEDS_MAX_SELECTION, OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_question import FirstQuestion, first_question_cache_key
from app.utils.artifact_utils import artifact_url_base


def ctx(
    *,
    user_id: str | None = "user1",
    query: str | None = "q",
    active_todo_id: str | None = None,
    execution_mode: ExecutionMode = "interactive",
    user_preferences: dict[str, Any] | None = None,
    source: str | None = None,
) -> SectionContext:
    """Build a comms context carrying everything these sections read, minus overrides."""
    return SectionContext(
        tier=AgentTier.COMMS,
        user_id=user_id,
        query=query,
        active_todo_id=active_todo_id,
        execution_mode=execution_mode,
        user_preferences=user_preferences,
        source=source,
    )


@pytest.mark.unit
class TestMemoryRecallBlock:
    async def test_renders_every_memory_with_its_date(self) -> None:
        """Asserted as the exact block, not substrings — the header and bullets are what keep two memories from reading as one sentence."""
        results = MemorySearchResult(
            memories=[
                memory("User likes coffee", mentioned="2026-01-05"),
                memory("User prefers dark mode", mentioned="2026-02-11"),
            ],
            total_count=2,
        )
        with patch("app.memory.engine.memory_engine.recall", AsyncMock(return_value=results)):
            block = await build_memory_recall_block(ctx(query="coffee"))

        assert block == (
            f"{MEMORY_RECALL_HEADER}\n"
            "- User likes coffee [mentioned 2026-01-05]\n"
            "- User prefers dark mode [mentioned 2026-02-11]"
        )

    async def test_it_recalls_against_this_turn_for_this_user(self) -> None:
        """Recalling on the wrong user or ignoring the query returns someone else's memories."""
        recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))
        with patch("app.memory.engine.memory_engine.recall", recall):
            await build_memory_recall_block(ctx(user_id="user-7", query="what did I promise?"))

        recall.assert_awaited_once_with("user-7", "what did I promise?", limit=5)

    async def test_a_failed_shared_recall_falls_back_to_the_executors_own_query(self) -> None:
        found = MemorySearchResult(
            memories=[memory("User's manager is Priya")], total_count=1, has_confident_match=True
        )
        recall = AsyncMock(side_effect=[RuntimeError("cache down"), found])
        executor = SectionContext(
            tier=AgentTier.EXECUTOR, user_id="user-7", query="the brief", request_query="yes"
        )
        with patch("app.memory.engine.memory_engine.recall", recall):
            block = await build_memory_recall_block(executor)

        assert "User's manager is Priya" in block
        assert recall.await_args_list[-1].args == ("user-7", "the brief")

    async def test_a_confident_recall_on_the_request_is_reused_instead_of_recalling_the_brief(
        self,
    ) -> None:
        """Comms already recalled on what the user said; the brief's own recall would only add noise its template words match."""
        found = MemorySearchResult(
            memories=[memory("User's manager is Priya")], total_count=1, has_confident_match=True
        )
        recall = AsyncMock(return_value=found)
        executor = SectionContext(
            tier=AgentTier.EXECUTOR,
            user_id="user-7",
            query="the brief",
            request_query="who is Priya",
        )
        async with captured_wide_event() as event:
            with patch("app.memory.engine.memory_engine.recall", recall):
                block = await build_memory_recall_block(executor)

        assert "User's manager is Priya" in block
        recall.assert_awaited_once_with("user-7", "who is Priya", limit=5)
        assert event["dynamic_context"]["memory_recall_reused"] is True

    async def test_a_request_that_matched_nothing_confidently_earns_the_brief_its_own_recall(
        self,
    ) -> None:
        """A bare "yes do it" recalls nothing useful; the brief carries the real subject, so it recalls on that."""
        weak = MemorySearchResult(
            memories=[memory("User said yes once")], total_count=1, has_confident_match=False
        )
        own = MemorySearchResult(
            memories=[memory("User's manager is Priya")], total_count=1, has_confident_match=True
        )
        recall = AsyncMock(side_effect=[weak, own])
        executor = SectionContext(
            tier=AgentTier.EXECUTOR, user_id="user-7", query="the brief", request_query="yes do it"
        )
        async with captured_wide_event() as event:
            with patch("app.memory.engine.memory_engine.recall", recall):
                block = await build_memory_recall_block(executor)

        assert "User's manager is Priya" in block
        assert "User said yes once" not in block
        assert [c.args for c in recall.await_args_list] == [
            ("user-7", "yes do it"),
            ("user-7", "the brief"),
        ]
        assert event["dynamic_context"]["memory_recall_reused"] is False

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

    async def test_a_failed_recall_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.memory.engine.memory_engine.recall",
                AsyncMock(side_effect=RuntimeError("chroma down")),
            ):
                await build_memory_recall_block(ctx(user_id="user-7"))

        assert event["warnings"] == [
            {
                "msg": "Error retrieving memories",
                "error": "chroma down",
                "error_type": "RuntimeError",
                "user_id": "user-7",
            }
        ]


@pytest.mark.unit
class TestCoreMemoryBlock:
    async def test_renders_the_core_context(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(return_value="- Ships on Fridays"),
        ):
            block = await build_core_memory_block(ctx())

        assert block == f"{CORE_MEMORY_HEADER}\n- Ships on Fridays"

    async def test_it_reads_the_core_for_this_user(self) -> None:
        core = AsyncMock(return_value="")
        with patch("app.memory.engine.memory_engine.get_core_context", core):
            await build_core_memory_block(ctx(user_id="user-7"))

        core.assert_awaited_once_with("user-7")

    async def test_empty_core_context_yields_no_block(self) -> None:
        with patch("app.memory.engine.memory_engine.get_core_context", AsyncMock(return_value="")):
            assert await build_core_memory_block(ctx()) == ""

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            assert await build_core_memory_block(ctx()) == ""

    async def test_failure_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.memory.engine.memory_engine.get_core_context",
                AsyncMock(side_effect=RuntimeError("redis down")),
            ):
                await build_core_memory_block(ctx(user_id="user-7"))

        assert event["warnings"] == [
            {
                "msg": "Error retrieving core memory context",
                "error": "redis down",
                "error_type": "RuntimeError",
                "user_id": "user-7",
            }
        ]


@pytest.mark.unit
class TestGaiaKnowledgeBlock:
    async def test_renders_each_result(self) -> None:
        """Two results, not one: with a single item the \\n joining them would be unobservable."""
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(
                return_value=[
                    knowledge("Gaia can manage calendar"),
                    knowledge("Gaia can run scheduled workflows"),
                ]
            ),
        ):
            block = await build_gaia_knowledge_block(ctx(query="calendar"))

        assert block == (
            f"{GAIA_KNOWLEDGE_HEADER}\n"
            "- Gaia can manage calendar\n"
            "- Gaia can run scheduled workflows"
        )

    async def test_it_searches_on_this_turns_query(self) -> None:
        search = AsyncMock(return_value=[])
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge", search
        ):
            await build_gaia_knowledge_block(ctx(query="what can you do?"))

        search.assert_awaited_once_with(query="what can you do?", limit=5)

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

    async def test_failure_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
                AsyncMock(side_effect=RuntimeError("chroma fail")),
            ):
                await build_gaia_knowledge_block(ctx())

        assert event["warnings"] == [
            {
                "msg": "Error retrieving GAIA knowledge",
                "error": "chroma fail",
                "error_type": "RuntimeError",
            }
        ]


def _tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


@pytest.mark.unit
class TestConnectedIntegrationsManifest:
    @pytest.fixture(autouse=True)
    def no_tools_by_default(self) -> Iterator[AsyncMock]:
        """Pin the bare shape; the tool summary has its own tests."""
        with patch(
            "app.agents.context.fetchers.get_integration_tool_list", AsyncMock(return_value=[])
        ) as lister:
            yield lister

    async def test_a_row_names_what_the_connection_is_for(
        self, no_tools_by_default: AsyncMock
    ) -> None:
        """The row GitHub (github) tells the model nothing it can act on — the tool count and sample turn it into something actionable."""
        no_tools_by_default.return_value = [
            _tool("GITHUB_CREATE_AN_ISSUE"),
            _tool("GITHUB_LIST_PULL_REQUESTS"),
            _tool("GITHUB_GET_A_COMMIT"),
        ]
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[{"id": "github", "name": "GitHub"}]),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == (
            "HEADER:\n- GitHub (github): 3 tools, e.g. create an issue, list pull requests, "
            "get a commit"
        )
        no_tools_by_default.assert_awaited_once_with("github")

    async def test_the_sample_is_capped_but_the_count_is_not(
        self, no_tools_by_default: AsyncMock
    ) -> None:
        no_tools_by_default.return_value = [_tool(f"GITHUB_ACTION_{i}") for i in range(12)]
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[{"id": "github", "name": "GitHub"}]),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == (
            "HEADER:\n- GitHub (github): 12 tools, e.g. action 0, action 1, action 2, action 3, action 4"
        )

    async def test_a_tool_listing_failure_keeps_the_bare_row_and_is_logged(
        self, no_tools_by_default: AsyncMock
    ) -> None:
        no_tools_by_default.side_effect = RuntimeError("registry cold")
        with (
            patch(
                "app.agents.context.fetchers.get_connected_integrations_named",
                AsyncMock(return_value=[{"id": "github", "name": "GitHub"}]),
            ),
            patch("app.agents.context.fetchers.log") as mock_log,
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == "HEADER:\n- GitHub (github)"
        assert mock_log.warning.call_args.args == (
            "Could not list tools for a connected integration; manifest row stays bare",
        )
        assert mock_log.warning.call_args.kwargs == {
            "integration_id": "github",
            "error": "registry cold",
            "error_type": "RuntimeError",
        }

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
        """A lone header would read like a fetch failure, not an empty list."""
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

    async def test_a_connected_task_provider_does_not_mask_the_builtin_todo_list(self) -> None:
        """Prod bug: with Todoist connected, the executor read "the user's todo list" as Todoist and reported GAIA todos as done in Todoist."""
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[{"id": "todoist", "name": "Todoist"}]),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == (
            "HEADER:\n- Todos: GAIA's own todo list, not Todoist (todos)\n- Todoist (todoist)"
        )

    async def test_the_builtin_row_names_every_provider_it_is_confused_with(self) -> None:
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(
                return_value=[
                    {"id": "googletasks", "name": "Google Tasks"},
                    {"id": "todoist", "name": "Todoist"},
                ]
            ),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert "- Todos: GAIA's own todo list, not Google Tasks or Todoist (todos)" in manifest

    async def test_no_overlapping_provider_means_no_builtin_row(self) -> None:
        """A built-in is spelled out only where something connected could be mistaken for it."""
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(return_value=[{"id": "gmail", "name": "Gmail"}]),
        ) as named:
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == "HEADER:\n- Gmail (gmail)"
        named.assert_awaited_once_with("u1")

    async def test_two_ids_for_one_provider_render_once_under_the_resolved_name(self) -> None:
        """A stale google_calendar beside today's googlecalendar rendered both, one a bare id resolving to no subagent."""
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named",
            AsyncMock(
                return_value=[
                    {"id": "google_calendar", "name": "google_calendar"},
                    {"id": "googlecalendar", "name": "Google Calendar"},
                ]
            ),
        ):
            manifest = await build_connected_integrations_manifest("u1", header="HEADER:")

        assert manifest == "HEADER:\n- Google Calendar (googlecalendar)"


@pytest.mark.unit
class TestDedupeByProvider:
    def test_a_real_name_already_held_is_never_displaced_by_an_id_named_duplicate(
        self,
    ) -> None:
        """A later id-only entry for the same provider must not clobber an earlier resolved display name."""
        items = [
            {"id": "slack", "name": "Slack Workspace"},
            {"id": "sl_ack", "name": "sl_ack"},
        ]

        assert _dedupe_by_provider(items) == [{"id": "slack", "name": "Slack Workspace"}]

    def test_an_id_named_entry_held_first_is_replaced_once_a_real_name_arrives(self) -> None:
        items = [
            {"id": "slack", "name": "slack"},
            {"id": "sl_ack", "name": "Slack Workspace"},
        ]

        assert _dedupe_by_provider(items) == [{"id": "sl_ack", "name": "Slack Workspace"}]

    def test_the_first_real_name_wins_over_a_second_equally_real_name(self) -> None:
        """Once a provider has resolved to ANY display name, a second row for it must not overwrite it, even with another real name."""
        items = [
            {"id": "calendar", "name": "Calendar One"},
            {"id": "cal_endar", "name": "Calendar Two"},
        ]

        assert _dedupe_by_provider(items) == [{"id": "calendar", "name": "Calendar One"}]

    def test_distinct_providers_are_all_kept_in_first_seen_order(self) -> None:
        items = [
            {"id": "gmail", "name": "Gmail"},
            {"id": "slack", "name": "Slack"},
            {"id": "notion", "name": "Notion"},
        ]

        assert _dedupe_by_provider(items) == items


@pytest.mark.unit
class TestTrackedTodosBlock:
    async def test_the_requesting_user_and_bound_todo_reach_the_summary(self) -> None:
        """The user and this run's bound todo reach the summary; a dropped id pins nothing."""
        summary = AsyncMock(return_value="Tracked: ship the refactor")
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            summary,
        ):
            block = await build_tracked_todos_block(ctx(user_id="user-7", active_todo_id="todo-7"))

        assert block == "Tracked: ship the refactor"
        summary.assert_awaited_once_with("user-7", active_todo_id="todo-7")

    async def test_failure_yields_no_block(self) -> None:
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_tracked_todos_block(ctx()) == ""

    async def test_a_pinned_view_failing_yields_no_block(self) -> None:
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_tracked_todos_block(ctx(active_todo_id="todo-7")) == ""


def _tracked_doc(todo_id: str, title: str) -> TodoDocument:
    now = datetime.now(UTC)
    return TodoDocument(
        id=todo_id,
        user_id="user1",
        title=title,
        labels=[GAIA_TRACKED_LABEL],
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(hours=1),
    )


@pytest.fixture
def repo_reads() -> AsyncMock:
    """Fake the repository's Mongo read with the cached_query cache seams faked.

    The active-tracked finder is generation-cached; these fakes stand in for the
    two Redis round trips (generation + query store) so the real decorator runs
    without Redis. Returns the _find spy, whose await count is the Mongo reads.
    """
    find = AsyncMock(return_value=[])
    generation = {"value": 1}
    store: dict[str, object] = {}

    async def _read_generation(_policy: object, _scope: str) -> int:
        return generation["value"]

    async def _get(key: str, model: object = None) -> object:
        return store.get(key)

    async def _set(key: str, value: object, ttl: int = 0, model: object = None) -> None:
        store[key] = value

    async def _bump(_policy: object, _scope: str) -> None:
        generation["value"] += 1

    with (
        patch.object(todo_repository, "_find", find),
        patch("app.db.repositories.base.read_generation", _read_generation),
        patch("app.db.repositories.base.get_cache", _get),
        patch("app.db.repositories.base.set_cache", _set),
        patch("app.db.repositories.base.bump_generation", _bump),
    ):
        yield find


@pytest.mark.unit
class TestTrackedTodosListIsTheCachedRead:
    """Pin that the active-tracked list is the cached read.

    A bound turn reads Mongo once per generation instead of once per assembly, and
    the bound todo is still pinned in memory after the (possibly cached) fetch.
    """

    async def test_two_bound_turns_read_mongo_once_and_still_pin(
        self, repo_reads: AsyncMock
    ) -> None:
        repo_reads.return_value = [
            _tracked_doc("todo-2", "Second"),
            _tracked_doc("todo-7", "Bound"),
        ]

        first = await build_tracked_todos_block(ctx(active_todo_id="todo-7"))
        second = await build_tracked_todos_block(ctx(active_todo_id="todo-7"))

        assert repo_reads.await_count == 1
        assert first == second
        lines = second.split("\n")
        assert lines[0] == "ACTIVE TRACKED TODOS:"
        assert lines[1].startswith('  ⭐ ACTIVE "Bound"')

    async def test_a_write_bumps_the_generation_and_the_next_turn_requeries(
        self, repo_reads: AsyncMock
    ) -> None:
        repo_reads.return_value = [_tracked_doc("todo-7", "Bound")]

        await build_tracked_todos_block(ctx(active_todo_id="todo-7"))
        await build_tracked_todos_block(ctx(active_todo_id="todo-7"))  # cached — no Mongo
        assert repo_reads.await_count == 1

        await todo_repository._invalidate("user1")  # what every todo write does
        await build_tracked_todos_block(ctx(active_todo_id="todo-7"))

        assert repo_reads.await_count == 2


async def _never_finishes() -> str:
    await asyncio.sleep(3600)
    return ""


@pytest.mark.unit
class TestCoreContextSingleFlight:
    """Pin that the two core-memory sections share one in-flight core fetch.

    They run in the same asyncio.gather, so they share rather than race; a task
    bound to a dead loop is never awaited cross-loop.
    """

    async def test_both_core_sections_share_one_fetch(self) -> None:
        calls = 0

        async def _core(user_id: str) -> str:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return f"Docs.\n\n{AGENDA_HEADING}\n- ship it\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed"

        with patch("app.memory.engine.memory_engine.get_core_context", _core):
            core_block, agenda_block = await asyncio.gather(
                build_core_memory_block(ctx()), build_agenda_and_activity_block(ctx())
            )

        assert calls == 1
        assert core_block == f"{CORE_MEMORY_HEADER}\nDocs."
        assert agenda_block == (
            f"{AGENDA_HEADING}\n- ship it\n\n{RECENT_ACTIVITY_HEADING}\n{MEMORY_IS_PAST_NOTE}\n- reviewed"
        )

    async def test_different_users_do_not_share_a_fetch(self) -> None:
        """Keyed by user, not just by loop, so one user's core never reaches another."""
        seen: list[str] = []

        async def _core(user_id: str) -> str:
            seen.append(user_id)
            await asyncio.sleep(0.05)
            return f"docs-for-{user_id}"

        with patch("app.memory.engine.memory_engine.get_core_context", _core):
            block_a, block_b = await asyncio.gather(
                build_core_memory_block(ctx(user_id="user-a")),
                build_core_memory_block(ctx(user_id="user-b")),
            )

        assert sorted(seen) == ["user-a", "user-b"]
        assert "docs-for-user-a" in block_a
        assert "docs-for-user-b" in block_b

    async def test_sequential_assemblies_each_read_afresh(self) -> None:
        """Once the in-flight fetch resolves it is gone, so the next assembly reads afresh."""
        calls = 0

        async def _core(user_id: str) -> str:
            nonlocal calls
            calls += 1
            return "Docs."

        with patch("app.memory.engine.memory_engine.get_core_context", _core):
            await build_core_memory_block(ctx())
            await build_core_memory_block(ctx())

        assert calls == 2

    async def test_cancelling_one_waiter_leaves_the_shared_fetch_running(self) -> None:
        """A cancelled assembly must not abort the sibling awaiting the same core fetch."""
        started = asyncio.Event()

        async def _core(user_id: str) -> str:
            started.set()
            await asyncio.sleep(0.05)
            return "Docs."

        with patch("app.memory.engine.memory_engine.get_core_context", _core):
            first = asyncio.ensure_future(build_core_memory_block(ctx()))
            second = asyncio.ensure_future(build_core_memory_block(ctx()))
            await started.wait()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert await second == f"{CORE_MEMORY_HEADER}\nDocs."

    async def test_the_inflight_entry_is_evicted_on_completion(self) -> None:
        """Eviction bounds the registry; a leak would keep every user's core context forever."""

        async def _core(user_id: str) -> str:
            return "Docs."

        with patch("app.memory.engine.memory_engine.get_core_context", _core):
            await build_core_memory_block(ctx())

        assert fetchers._inflight_core == {}

    def test_a_task_from_a_previous_loop_is_never_awaited(self) -> None:
        """A pending task left by a dead loop is ignored, never awaited cross-loop."""
        other_loop = asyncio.new_event_loop()
        stale = other_loop.create_task(_never_finishes())
        fetchers._inflight_core[(other_loop, "user1")] = stale
        fetched: list[str] = []

        async def _core(user_id: str) -> str:
            fetched.append(user_id)
            return "Docs."

        try:
            with patch("app.memory.engine.memory_engine.get_core_context", _core):
                block = asyncio.run(build_core_memory_block(ctx()))
            assert fetched == ["user1"]
            assert block == f"{CORE_MEMORY_HEADER}\nDocs."
        finally:
            fetchers._inflight_core.pop((other_loop, "user1"), None)
            stale.cancel()
            other_loop.run_until_complete(asyncio.sleep(0))
            other_loop.close()


@pytest.mark.unit
class TestNewUserGuidanceBlock:
    """The first-conversation playbooks: present only while the user is new, carrying only the needs they picked."""

    #: A ceiling, not a measurement — an edit that doubles the block should fail
    #: here rather than show up as a bill. Raised 3,400 -> 4,700 -> 6,600 -> 7,500
    #: as playbooks, persona-eval writing rules, and the connect-handoff line were added.
    MAX_BLOCK_CHARS = 7_500

    @staticmethod
    def _count(value: int) -> AsyncMock:
        return AsyncMock(return_value=value)

    def _patch_count(self, counter: AsyncMock) -> Any:
        return patch(
            "app.agents.context.fetchers.conversation_repository.count_non_onboarding", counter
        )

    async def test_renders_the_picked_needs_and_the_profession(self) -> None:
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["inbox"]})
            )
        assert NEED_PLAYBOOKS[OnboardingNeed.INBOX] in block
        assert "Founder" in block

    async def test_a_need_they_did_not_pick_never_reaches_the_model(self) -> None:
        """A user who ticked one box carries one playbook, not the catalogue they'd have to be told to ignore."""
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Student", "needs": ["calendar"]})
            )
        assert NEED_PLAYBOOKS[OnboardingNeed.CALENDAR] in block
        assert NEED_PLAYBOOKS[OnboardingNeed.INBOX] not in block

    async def test_one_need_alone_is_enough_to_render(self) -> None:
        with self._patch_count(self._count(0)):
            assert await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["grunt_work"]})
            )

    async def test_the_typed_need_reaches_the_model_in_their_words(self) -> None:
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(
                    user_preferences={
                        "profession": "Founder",
                        "needs": ["inbox"],
                        "other_need": "chasing invoices",
                    }
                )
            )
        assert '"chasing invoices"' in block
        assert NEED_PLAYBOOKS[OnboardingNeed.INBOX] in block

    async def test_a_typed_need_alone_is_enough_to_render(self) -> None:
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "other_need": "chasing invoices"})
            )
        assert block == build_new_user_guidance("Founder", [], "chasing invoices")

    async def test_a_non_string_typed_need_is_ignored(self) -> None:
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["inbox"], "other_need": 7})
            )
        assert block == build_new_user_guidance("Founder", [OnboardingNeed.INBOX])

    async def test_a_non_string_typed_need_is_passed_as_none_not_empty(self) -> None:
        """The playbook builder gets None, so it never renders an empty quote."""
        with (
            self._patch_count(self._count(1)),
            patch(
                "app.agents.context.fetchers.build_new_user_guidance", return_value="block"
            ) as build,
        ):
            await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["inbox"], "other_need": 7})
            )
        build.assert_called_once_with("Founder", [OnboardingNeed.INBOX], None, [])

    async def test_the_block_stops_once_the_user_is_no_longer_new(self) -> None:
        with self._patch_count(self._count(NEW_USER_CONVERSATION_LIMIT + 1)):
            assert (
                await build_new_user_guidance_block(
                    ctx(user_preferences={"profession": "Founder", "needs": ["inbox"]})
                )
                == ""
            )

    async def test_the_last_new_conversation_still_renders(self) -> None:
        """Pins the boundary: an off-by-one here silently drops the block a conversation early."""
        with self._patch_count(self._count(NEW_USER_CONVERSATION_LIMIT)):
            assert await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["inbox"]})
            )

    async def test_no_needs_means_no_block_and_no_lookup(self) -> None:
        """Users who predate the signup questions must not pay for the count."""
        counter = self._count(0)
        with self._patch_count(counter):
            assert (
                await build_new_user_guidance_block(ctx(user_preferences={"profession": "Founder"}))
                == ""
            )
        counter.assert_not_awaited()

    async def test_no_preferences_at_all_means_no_block(self) -> None:
        assert await build_new_user_guidance_block(ctx()) == ""

    async def test_an_unknown_need_is_skipped_rather_than_dropping_the_block(self) -> None:
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["telepathy", "reminders"]})
            )
        assert NEED_PLAYBOOKS[OnboardingNeed.REMINDERS] in block

    async def test_a_skipped_need_names_itself_in_the_wide_event(self) -> None:
        """The warning is the only trace that a rename left users unserved — silently dropping looks identical to never picking it."""
        async with captured_wide_event() as event:
            with self._patch_count(self._count(1)):
                await build_new_user_guidance_block(
                    ctx(
                        user_preferences={
                            "profession": "Founder",
                            "needs": ["telepathy", "reminders"],
                        }
                    )
                )

        assert event["warnings"] == [
            {"msg": "Unknown onboarding need in preferences", "need": "telepathy"}
        ]

    async def test_a_user_with_no_profession_still_gets_their_playbooks(self) -> None:
        """The profession is optional; its absence must not leak a placeholder into the prompt."""
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(ctx(user_preferences={"needs": ["inbox"]}))
        assert block == build_new_user_guidance("", [OnboardingNeed.INBOX])

    async def test_a_failed_count_yields_no_block(self) -> None:
        with self._patch_count(AsyncMock(side_effect=RuntimeError("mongo down"))):
            assert (
                await build_new_user_guidance_block(
                    ctx(user_preferences={"profession": "Founder", "needs": ["inbox"]})
                )
                == ""
            )

    async def test_a_failed_count_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with self._patch_count(AsyncMock(side_effect=RuntimeError("mongo down"))):
                await build_new_user_guidance_block(
                    ctx(
                        user_id="user-9",
                        user_preferences={"profession": "Founder", "needs": ["inbox"]},
                    )
                )

        assert event["warnings"] == [
            {
                "msg": "Error counting conversations for new-user guidance",
                "error": "mongo down",
                "error_type": "RuntimeError",
                "user_id": "user-9",
            }
        ]

    async def test_the_conversation_count_is_scoped_to_this_user(self) -> None:
        """Counting someone else's conversations would keep the block alive past the point this user stopped being new."""
        counter = self._count(1)
        with self._patch_count(counter):
            await build_new_user_guidance_block(
                ctx(
                    user_id="user-9", user_preferences={"profession": "Founder", "needs": ["inbox"]}
                )
            )
        counter.assert_awaited_once_with("user-9")

    async def test_every_need_has_a_playbook(self) -> None:
        assert set(NEED_PLAYBOOKS) == set(OnboardingNeed)

    async def test_each_playbook_is_its_own_bullet_line(self) -> None:
        """Two needs are two lines; run together, the model reads one malformed bullet instead of two instructions."""
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(
                ctx(user_preferences={"profession": "Founder", "needs": ["inbox", "reminders"]})
            )
        assert (
            f"- {NEED_PLAYBOOKS[OnboardingNeed.INBOX]}\n- {NEED_PLAYBOOKS[OnboardingNeed.REMINDERS]}"
            in block
        )

    async def test_a_user_who_skipped_the_profession_is_addressed_as_a_person(self) -> None:
        """The template interpolates the profession three times; an unset Q1 must render a plain noun, not an empty hole."""
        with self._patch_count(self._count(1)):
            block = await build_new_user_guidance_block(ctx(user_preferences={"needs": ["inbox"]}))
        assert block.startswith("FIRST CONVERSATIONS (you just met this person)")
        assert "do for a person" in block
        assert "the way a person talks" in block

    async def test_no_needs_renders_nothing_rather_than_a_headerless_block(self) -> None:
        """A block with an empty playbook list is the generic coaching this section exists to replace, so it must be empty string."""
        assert build_new_user_guidance("Founder", []) == ""

    async def test_the_chips_rule_names_the_chips_that_were_offered(self) -> None:
        """The model has to see the exact words it offered, or a one-word first message reads as a fragment."""
        block = build_new_user_guidance("Founder", [OnboardingNeed.INBOX], None, ["My mornings"])
        assert '"My mornings"' in block

    async def test_no_chips_renders_no_chips_rule(self) -> None:
        """An expired cache must not tell the model a choice was offered."""
        block = build_new_user_guidance("Founder", [OnboardingNeed.INBOX], None, [])
        assert "You already asked them a question" not in block

    async def test_the_chips_are_looked_up_under_this_user_and_these_exact_answers(
        self,
    ) -> None:
        """The chips live under a key built from the user id and the three answers; any going astray silently loses the chips rule."""
        with (
            self._patch_count(self._count(1)),
            patch("app.agents.context.fetchers.seeded_chips", AsyncMock(return_value=[])) as chips,
        ):
            await build_new_user_guidance_block(
                ctx(
                    user_id="user-9",
                    user_preferences={
                        "profession": "Founder",
                        "needs": ["inbox"],
                        "other_need": "chasing invoices",
                    },
                )
            )

        chips.assert_awaited_once_with(
            "user-9",
            OnboardingPreferences(
                profession="Founder",
                needs=[OnboardingNeed.INBOX],
                other_need="chasing invoices",
            ),
        )

    async def test_the_chips_the_seeded_turn_offered_reach_the_model(self) -> None:
        """End to end through the real cache-key derivation: what the seeded conversation wrote is what the block quotes back."""
        cached = FirstQuestion(question="What should we start with?", chips=["My mornings"])
        preferences = OnboardingPreferences(
            profession="Founder",
            needs=[OnboardingNeed.INBOX],
            other_need="chasing invoices",
        )
        with (
            self._patch_count(self._count(1)),
            patch(
                "app.services.onboarding.first_question.redis_cache.get",
                AsyncMock(return_value=cached),
            ) as cache_get,
        ):
            block = await build_new_user_guidance_block(
                ctx(
                    user_id="user-9",
                    user_preferences={
                        "profession": "Founder",
                        "needs": ["inbox"],
                        "other_need": "chasing invoices",
                    },
                )
            )

        assert cache_get.await_args.args[0] == first_question_cache_key("user-9", preferences)
        assert '"My mornings"' in block

    async def test_the_block_is_the_template_filled_with_every_one_of_its_slots(self) -> None:
        """Asserted whole rather than by substring: a slot filled with the wrong value still renders a plausible-looking block."""
        block = build_new_user_guidance(
            "Founder", [OnboardingNeed.INBOX], None, ["My mornings", "Growth"]
        )

        assert block == NEW_USER_GUIDANCE_TEMPLATE.format(
            profession="Founder",
            playbooks=f"- {NEED_PLAYBOOKS[OnboardingNeed.INBOX]}",
            target=TARGET_REPLY_EXAMPLE,
            chips_rule=SEEDED_CHIPS_RULE.format(chips='"My mornings", "Growth"'),
        )

    async def test_two_chips_are_quoted_and_comma_separated(self) -> None:
        """The model has to read them as two distinct offers, not one nonsense phrase run together."""
        block = build_new_user_guidance(
            "Founder", [OnboardingNeed.INBOX], None, ["My mornings", "Late payers"]
        )

        assert '"My mornings", "Late payers"' in block

    async def test_a_user_offered_no_chips_gets_the_slot_closed_up_entirely(self) -> None:
        """The empty case is a slot filled with nothing, not a placeholder — any residue reads to the model as an instruction."""
        block = build_new_user_guidance("Founder", [OnboardingNeed.INBOX], None, [])

        assert block == NEW_USER_GUIDANCE_TEMPLATE.format(
            profession="Founder",
            playbooks=f"- {NEED_PLAYBOOKS[OnboardingNeed.INBOX]}",
            target=TARGET_REPLY_EXAMPLE,
            chips_rule="",
        )

    async def test_the_worst_case_block_stays_within_budget(self) -> None:
        """The two longest playbooks (the API caps picks at two), plus four seeded chips and a typed need, is the largest case."""
        longest = sorted(OnboardingNeed, key=lambda n: len(NEED_PLAYBOOKS[n]), reverse=True)
        block = build_new_user_guidance(
            "Founder",
            longest[:NEEDS_MAX_SELECTION],
            "chasing invoices",
            ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"],
        )
        assert len(block) <= self.MAX_BLOCK_CHARS, f"guidance block grew to {len(block)} chars"


@pytest.mark.unit
class TestWorkspaceSessionBanner:
    async def test_states_both_the_directory_and_the_public_url(self) -> None:
        """Missing either the directory or the URL base makes the agent guess, and a wrong path is a silent failure."""
        banner = await build_workspace_session_banner(
            SectionContext(tier=AgentTier.EXECUTOR, vfs_session_id="sess-1")
        )

        assert banner == (
            f"Session directory: {session_dir('sess-1')}\n"
            "Public artifact URL: a file at `artifacts/<name>` is served at "
            f"{artifact_url_base('sess-1')}/<name>"
        )

    async def test_no_vfs_session_id_never_guesses_a_directory(self) -> None:
        """A fallback to thread_id would name executor_<conv>, outside the directory the artifact watcher scans."""
        banner = await build_workspace_session_banner(
            SectionContext(tier=AgentTier.EXECUTOR, vfs_session_id=None)
        )

        assert banner == ""


@pytest.mark.unit
class TestActiveTodoBanner:
    async def test_it_states_the_binding_the_write_target_and_the_escape_hatch(self) -> None:
        """Asserting only two substrings let the rest rot into nonsense unnoticed."""
        todo = TodoDocument(
            id="66f838cc8829054e5f10e407", user_id="user1", title="Ship the refactor"
        )
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=todo)):
            banner = await build_active_todo_banner(ctx(active_todo_id=todo.id))

        assert banner == format_active_todo_banner(todo)
        assert banner == (
            "🎯 ACTIVE TODO (this run is bound to this todo)\n"
            "   id: 66f838cc8829054e5f10e407\n"
            "   title: Ship the refactor\n"
            "   files: /workspace/gaia-tasks/ship-the-refactor-5f10e407/canvas.md, "
            "/workspace/gaia-tasks/ship-the-refactor-5f10e407/activity.md\n"
            "\n"
            "   Default write target for this turn: this todo's files.\n"
            "   - Read canvas.md first. Record progress and outcomes as a dated entry at the end "
            "of activity.md; keep Current State in canvas.md true; learnings go in canvas.md.\n"
            "   - Use `add_memory(...)` ONLY for durable cross-cutting facts unrelated to this "
            "todo (rare).\n"
            "   - To work on a different todo, you must reference it explicitly by id."
        )

    def test_an_untitled_todo_still_renders_a_usable_banner(self) -> None:
        """A blank title would leave the line dangling; the agent still needs the id, the part it acts on."""
        banner = format_active_todo_banner(TodoDocument(id="todo-9", user_id="user1", title=""))

        assert "   id: todo-9\n" in banner
        assert "   title: Untitled\n" in banner

    async def test_it_reads_the_bound_todo_scoped_to_its_owner(self) -> None:
        """Unscoped, a guessed id would surface another user's todo."""
        get = AsyncMock(return_value=None)
        with patch("app.db.repositories.todos.todo_repository.get", get):
            await build_active_todo_banner(ctx(user_id="user-7", active_todo_id="todo-7"))

        get.assert_awaited_once_with("todo-7", user_id="user-7")

    async def test_a_missing_todo_yields_no_banner(self) -> None:
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=None)):
            assert await build_active_todo_banner(ctx(active_todo_id="gone")) == ""

    async def test_failure_yields_no_banner(self) -> None:
        with patch(
            "app.db.repositories.todos.todo_repository.get",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await build_active_todo_banner(ctx(active_todo_id="todo-7")) == ""

    async def test_failure_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.db.repositories.todos.todo_repository.get",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ):
                await build_active_todo_banner(ctx(active_todo_id="todo-7"))

        assert event["warnings"] == [
            {"msg": "active_todo_banner_fetch_failed", "error": "mongo down"}
        ]


@pytest.mark.unit
class TestBackgroundBanner:
    async def test_a_background_run_is_told_no_human_is_reading(self) -> None:
        banner = await build_background_banner(ctx(execution_mode="background"))

        assert "BACKGROUND EXECUTION" in banner

    async def test_an_interactive_run_gets_no_banner(self) -> None:
        assert await build_background_banner(ctx()) == ""


@pytest.mark.unit
class TestASectionDeclinesWhenItsContextIsAbsent:
    """Every source below is patched to return real content on purpose: left unpatched, a broken precondition would raise and be swallowed into the same "" these tests assert, passing whether the guard worked or not."""

    async def test_no_user_means_no_core_memory(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(return_value="- Ships on Fridays"),
        ):
            assert await build_core_memory_block(ctx(user_id=None)) == ""

    @pytest.mark.parametrize("missing", [{"user_id": None}, {"query": None}])
    async def test_recall_needs_both_a_user_and_a_query(self, missing: dict[str, None]) -> None:
        results = MemorySearchResult(memories=[memory("User likes coffee")], total_count=1)
        with patch("app.memory.engine.memory_engine.recall", AsyncMock(return_value=results)):
            assert await build_memory_recall_block(ctx(**missing)) == ""

    async def test_no_query_means_no_knowledge_lookup(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[knowledge("Gaia can manage calendar")]),
        ):
            assert await build_gaia_knowledge_block(ctx(query=None)) == ""

    async def test_no_user_means_no_tracked_todos(self) -> None:
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            AsyncMock(return_value="Tracked: ship the refactor"),
        ):
            assert await build_tracked_todos_block(ctx(user_id=None)) == ""

    @pytest.mark.parametrize("missing", ["user_id", "active_todo_id"])
    async def test_the_active_todo_banner_needs_both_ids(self, missing: str) -> None:
        todo = TodoDocument(id="todo-7", user_id="user1", title="Ship the refactor")
        present: dict[str, str | None] = {"user_id": "user1", "active_todo_id": "todo-7"}
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=todo)):
            assert await build_active_todo_banner(ctx(**{**present, missing: None})) == ""


@pytest.mark.unit
class TestSplitOffSection:
    """How the memory core is divided into its stable and churning halves."""

    def test_a_heading_splits_the_body_off_the_documents(self) -> None:
        before, body = _split_off_section(
            f"Loves espresso.\n\n{AGENDA_HEADING}\n- ship it", AGENDA_HEADING
        )

        assert before == "Loves espresso."
        assert body == "\n- ship it"

    def test_a_heading_that_opens_the_core_leaves_nothing_stable(self) -> None:
        """Requiring the blank line ahead of the heading previously filed a churning first section as stable."""
        before, body = _split_off_section(f"{AGENDA_HEADING}\n- ship it", AGENDA_HEADING)

        assert before == ""
        assert body == "\n- ship it"

    def test_a_heading_quoted_again_inside_the_body_splits_at_the_first_one(self) -> None:
        """Section bodies are user memory text and can repeat a heading; the split takes the first occurrence only."""
        before, body = _split_off_section(
            f"Loves espresso.\n\n{AGENDA_HEADING}\n- ship it\n\n{AGENDA_HEADING}\n- and again",
            AGENDA_HEADING,
        )

        assert before == "Loves espresso."
        assert body == f"\n- ship it\n\n{AGENDA_HEADING}\n- and again"

    def test_an_absent_heading_leaves_the_core_whole(self) -> None:
        before, body = _split_off_section("Loves espresso.", AGENDA_HEADING)

        assert before == "Loves espresso."
        assert body == ""


@pytest.mark.unit
class TestTheMemoryCoreSplit:
    """get_core_context renders documents, agenda and journal as one string; only the documents are byte-stable, so the three split across two slots."""

    @staticmethod
    def _core(core: str) -> Any:
        return patch(
            "app.memory.engine.memory_engine.get_core_context", AsyncMock(return_value=core)
        )

    async def test_the_documents_alone_are_the_stable_block(self) -> None:
        core = (
            "Loves espresso."
            f"\n\n{AGENDA_HEADING}\n- ship the cache work"
            f"\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        )
        with self._core(core):
            assert await build_core_memory_block(ctx()) == f"{CORE_MEMORY_HEADER}\nLoves espresso."

    async def test_the_agenda_and_the_journal_are_the_volatile_block(self) -> None:
        core = (
            "Loves espresso."
            f"\n\n{AGENDA_HEADING}\n- ship the cache work"
            f"\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        )
        with self._core(core):
            block = await build_agenda_and_activity_block(ctx())

        assert block == (
            f"{AGENDA_HEADING}\n- ship the cache work\n\n"
            f"{RECENT_ACTIVITY_HEADING}\n{MEMORY_IS_PAST_NOTE}\n- reviewed a PR"
        )

    async def test_a_core_with_no_documents_still_yields_its_volatile_half(self) -> None:
        """Filling the stable slot from "whatever came first" put a churning section in the cached prefix for unconsolidated users."""
        with self._core(f"{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"):
            assert await build_core_memory_block(ctx()) == ""
            assert "- reviewed a PR" in await build_agenda_and_activity_block(ctx())

    def test_the_agenda_does_not_swallow_the_journal(self) -> None:
        """Split from the back: get_core_context emits the agenda before the journal, so splitting on the agenda first would swallow the journal into it."""
        core = (
            "Loves espresso."
            f"\n\n{AGENDA_HEADING}\n- ship the cache work"
            f"\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        )

        documents, agenda, activity = _split_core_context(core)

        assert documents == "Loves espresso."
        assert agenda == "\n- ship the cache work"
        assert activity == "\n- reviewed a PR"

    async def test_the_stable_documents_are_never_capped(self) -> None:
        """Truncating them would churn the cached prefix every time the core grew."""
        documents = "\n".join(f"- fact {i}" for i in range(500))
        with self._core(documents):
            block = await build_core_memory_block(ctx())

        assert block == f"{CORE_MEMORY_HEADER}\n{documents}"

    async def test_a_failed_core_read_costs_both_halves_and_nothing_else(self) -> None:
        with patch(
            "app.memory.engine.memory_engine.get_core_context",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            assert await build_core_memory_block(ctx()) == ""
            assert await build_agenda_and_activity_block(ctx()) == ""

    async def test_an_empty_core_yields_no_blocks_at_all(self) -> None:
        """Both halves of the split come back empty, rather than one manufacturing a header over nothing."""
        with self._core(""):
            assert await build_core_memory_block(ctx()) == ""
            assert await build_agenda_and_activity_block(ctx()) == ""

    async def test_a_long_agenda_and_journal_both_survive_whole(self) -> None:
        """No section is clipped: what a provider caches is decided by where the volatile block sits, not by how long it is."""
        agenda = "\n".join(f"- commitment {i}" for i in range(200))
        journal = "\n".join(f"- did thing {i}" for i in range(200))
        core = (
            f"Loves espresso.\n\n{AGENDA_HEADING}\n{agenda}\n\n{RECENT_ACTIVITY_HEADING}\n{journal}"
        )
        with self._core(core):
            block = await build_agenda_and_activity_block(ctx())

        assert block == (
            f"{AGENDA_HEADING}\n{agenda}\n\n{RECENT_ACTIVITY_HEADING}\n{MEMORY_IS_PAST_NOTE}\n{journal}"
        )


@pytest.mark.unit
class TestNoVolatileSectionIsClipped:
    """Every fetched section reaches the model whole — the prompt cache is won by slot ordering, not by shortening what the agent sees."""

    async def test_a_long_recall_keeps_every_memory(self) -> None:
        memories = [memory("m" * 200, mentioned="2026-02-01") for _ in range(10)]
        with patch(
            "app.memory.engine.memory_engine.recall",
            AsyncMock(return_value=MemorySearchResult(memories=memories)),
        ):
            block = await build_memory_recall_block(ctx())

        notes = "\n".join("- " + "m" * 200 + " [mentioned 2026-02-01]" for _ in range(10))
        assert block == f"{MEMORY_RECALL_HEADER}\n{notes}"

    async def test_a_long_knowledge_result_is_rendered_whole(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[knowledge("k" * 400)]),
        ):
            block = await build_gaia_knowledge_block(ctx())

        assert block == f"{GAIA_KNOWLEDGE_HEADER}\n- {'k' * 400}"

    async def test_a_long_todo_summary_is_rendered_whole(self) -> None:
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            AsyncMock(return_value="t" * 400),
        ):
            block = await build_tracked_todos_block(ctx(active_todo_id="todo-1"))

        assert block == "t" * 400


@pytest.mark.unit
class TestOpenPendingsBlock:
    REVOKE_RULE = (
        'If a step is no longer needed, withdraw it with execute(tool_name="revoke", '
        'data={"id": "<id>"}).'
    )

    def _doc(
        self,
        approval_id: str = "ap_1",
        summary: str = "Send it",
        user_id: str = "u1",
        created_at: object = None,
    ) -> MagicMock:
        doc = MagicMock()
        doc.approval_id = approval_id
        doc.tool_name = "GMAIL_SEND_EMAIL"
        doc.summary = summary
        doc.user_id = user_id
        doc.created_at = datetime.now(UTC) - timedelta(days=3) if created_at is None else created_at
        return doc

    def _ctx(self, conversation_id: str | None = "c1") -> SectionContext:
        return SectionContext(
            tier=AgentTier.EXECUTOR, user_id="u1", conversation_id=conversation_id
        )

    async def _render(self, docs: list[MagicMock]) -> str:
        with patch(
            "app.agents.context.fetchers.approval_ledger_repository",
        ) as ledger:
            ledger.list_open = AsyncMock(return_value=docs)
            text = await build_open_pendings_block(self._ctx())
        ledger.list_open.assert_awaited_once_with("c1")
        return text

    async def test_renders_each_pending_with_age_and_revoke_rule(self) -> None:
        text = await self._render([self._doc(), self._doc("ap_2", "File it")])

        assert text == (
            "OPEN PENDINGS (awaiting the user's decision):\n"
            "- ap_1 | GMAIL_SEND_EMAIL | 3d | Send it\n"
            "- ap_2 | GMAIL_SEND_EMAIL | 3d | File it\n" + self.REVOKE_RULE
        )

    @pytest.mark.parametrize(
        ("age", "bucket"),
        [
            (timedelta(hours=1), "today"),
            (timedelta(days=1, hours=1), "1d"),
            (timedelta(days=4, hours=2), "4d"),
        ],
    )
    async def test_age_is_bucketed_to_the_day(self, age: timedelta, bucket: str) -> None:
        text = await self._render([self._doc(created_at=datetime.now(UTC) - age)])

        assert f"- ap_1 | GMAIL_SEND_EMAIL | {bucket} | Send it" in text.splitlines()

    async def test_a_row_without_a_timestamp_shows_an_unknown_age(self) -> None:
        text = await self._render([self._doc(created_at="not-a-datetime")])

        assert "- ap_1 | GMAIL_SEND_EMAIL | ? | Send it" in text.splitlines()

    async def test_caps_at_ten_with_overflow_count(self) -> None:
        docs = [self._doc(approval_id=f"ap_{i}", summary=f"s{i}") for i in range(12)]

        lines = (await self._render(docs)).splitlines()

        assert lines[-2:] == ["(+2 more open)", self.REVOKE_RULE]
        assert [line.split(" | ")[0] for line in lines[1:11]] == [f"- ap_{i}" for i in range(10)]

    async def test_exactly_ten_pendings_carry_no_overflow_line(self) -> None:
        docs = [self._doc(approval_id=f"ap_{i}") for i in range(10)]

        lines = (await self._render(docs)).splitlines()

        assert len(lines) == 12
        assert lines[-1] == self.REVOKE_RULE
        assert not any("more open" in line for line in lines)

    async def test_empty_and_missing_conversation_render_empty(self) -> None:
        with patch(
            "app.agents.context.fetchers.approval_ledger_repository",
        ) as ledger:
            ledger.list_open = AsyncMock(return_value=[])
            assert await build_open_pendings_block(self._ctx()) == ""
            assert await build_open_pendings_block(self._ctx(None)) == ""
            ledger.list_open.assert_awaited_once()

    async def test_ledger_failure_degrades_to_empty_and_is_logged(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.agents.context.fetchers.approval_ledger_repository",
            ) as ledger:
                ledger.list_open = AsyncMock(side_effect=ConnectionError("mongo down"))
                text = await build_open_pendings_block(self._ctx())

        assert text == ""
        assert event["warnings"] == [
            {"msg": "open_pendings_fetch_failed", "error_type": "ConnectionError"}
        ]

    async def test_foreign_rows_never_render_into_this_users_context(self) -> None:
        text = await self._render(
            [
                self._doc("ap_mine", "Mine"),
                self._doc("ap_theirs", "Theirs", user_id="u2"),
                self._doc("ap_legacy", "Legacy", user_id=""),
            ]
        )

        assert "ap_mine" in text
        assert "ap_theirs" not in text
        assert "ap_legacy" in text

    async def test_only_foreign_rows_render_nothing(self) -> None:
        text = await self._render([self._doc("ap_theirs", "Theirs", user_id="u2")])

        assert text == ""
