"""The section bodies behind the context table.

Every one of these degrades to ``""`` rather than raising, so the failure path
is the important half: a recall timeout must cost the user a thinner prompt, not
their whole turn. Each also declines to render at all when the context it needs
is absent — that precondition lives with the read rather than at the call site,
so no caller can forget it.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from tests._harness.context_sources import knowledge, memory
from tests.helpers import captured_wide_event

from app.agents.context.fetchers import (
    AGENDA_CAP_CHARS,
    GAIA_KNOWLEDGE_CAP_CHARS,
    MEMORIES_CAP_CHARS,
    RECENT_ACTIVITY_CAP_CHARS,
    TRACKED_TODOS_CAP_CHARS,
    _split_off_section,
    build_active_todo_banner,
    build_agenda_and_activity_block,
    build_background_banner,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_tracked_todos_block,
    build_workspace_session_banner,
    cap_section,
    format_active_todo_banner,
)
from app.agents.context.section_context import ExecutionMode, SectionContext
from app.agents.context.text import (
    AGENDA_TRUNC_MARKER,
    CORE_MEMORY_HEADER,
    GAIA_KNOWLEDGE_HEADER,
    GAIA_KNOWLEDGE_TRUNC_MARKER,
    MEMORIES_TRUNC_MARKER,
    MEMORY_RECALL_HEADER,
    RECENT_ACTIVITY_TRUNC_MARKER,
    TRACKED_TODOS_TRUNC_MARKER,
)
from app.agents.context.tiers import AgentTier
from app.agents.workspace.paths import session_dir
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.models.memory_models import MemorySearchResult
from app.models.todo_models import TodoDocument
from app.utils.artifact_utils import artifact_url_base


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
        has to be answerable from the injected text without another tool call.

        Asserted as the exact block rather than substrings — the header names
        what the dates mean, and the ``- `` bullets are what keep two memories
        from reading as one sentence. A substring check sees none of that.
        """
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
        """Recalling on the wrong user or ignoring the query returns someone
        else's memories, or this user's least relevant ones."""
        recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))
        with patch("app.memory.engine.memory_engine.recall", recall):
            await build_memory_recall_block(ctx(user_id="user-7", query="what did I promise?"))

        recall.assert_awaited_once_with("user-7", "what did I promise?", limit=5)

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
        """Two results, not one: with a single item the ``\\n`` joining them is
        unobservable, so a separator that stopped separating would read as two
        capabilities run together into one sentence and no test would notice."""
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
        the URL base to link what it wrote. Missing either makes it guess — and
        a wrong path is the silent failure, so both are pinned exactly."""
        banner = await build_workspace_session_banner(
            SectionContext(tier=AgentTier.EXECUTOR, vfs_session_id="sess-1")
        )

        assert banner == (
            f"Session directory: {session_dir('sess-1')}\n"
            "Public artifact URL: a file at `artifacts/<name>` is served at "
            f"{artifact_url_base('sess-1')}/<name>"
        )

    async def test_no_vfs_session_id_never_guesses_a_directory(self) -> None:
        """A fallback to ``thread_id`` would name ``executor_<conv>``, sending
        deliverables outside the directory the artifact watcher scans."""
        banner = await build_workspace_session_banner(
            SectionContext(tier=AgentTier.EXECUTOR, vfs_session_id=None)
        )

        assert banner == ""


@pytest.mark.unit
class TestActiveTodoBanner:
    async def test_it_states_the_binding_the_write_target_and_the_escape_hatch(self) -> None:
        """Every line here is an instruction the agent acts on: which todo the
        run is bound to, that the canvas is the default write target, the exact
        tool call to make, and that another todo needs an explicit id. Asserting
        two substrings left the rest free to rot into nonsense unnoticed."""
        todo = TodoDocument(id="todo-7", user_id="user1", title="Ship the refactor")
        with patch("app.db.repositories.todos.todo_repository.get", AsyncMock(return_value=todo)):
            banner = await build_active_todo_banner(ctx(active_todo_id="todo-7"))

        assert banner == format_active_todo_banner(todo)
        assert banner == (
            "🎯 ACTIVE TODO (this run is bound to this todo)\n"
            "   id: todo-7\n"
            "   title: Ship the refactor\n"
            "\n"
            "   Default write target for this turn: this todo's canvas.\n"
            '   - Use `update_tracked_todo_canvas(todo_id="todo-7", ...)` for any progress, '
            "outcome, or learning from this run.\n"
            "   - Use `add_memory(...)` ONLY for durable cross-cutting facts unrelated to this "
            "todo (rare).\n"
            "   - To work on a different todo, you must reference it explicitly by id."
        )

    def test_an_untitled_todo_still_renders_a_usable_banner(self) -> None:
        """A blank title would leave the line dangling; the agent still needs
        the id, which is the part it acts on."""
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
    """The precondition lives with the read, not at the call site, so a section
    registered directly against a fetcher cannot be given a context it needs and
    render a header over nothing.

    Every source below is patched to return real content on purpose. Left
    unpatched, a broken precondition would reach a store that is not there,
    raise, and be swallowed into the same ``""`` these tests assert — so they
    would pass whether the guard worked or not. Pinned this way, dropping the
    guard renders the content and the test goes red.
    """

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
            "app.agents.context.fetchers._cached_tracked_todos_summary",
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
class TestCapSection:
    """The size guard every volatile section shares."""

    def test_a_section_at_exactly_its_budget_is_untouched(self) -> None:
        text = "x" * 10

        assert cap_section(text, 10, "…marker…") == text

    def test_an_oversized_section_keeps_its_newest_tail_behind_the_marker(self) -> None:
        """The newest / most relevant content is at the END of every section this
        guards, so the tail is what survives."""
        assert cap_section("stale. " * 20 + "NEWEST", 6, "…marker…") == "…marker…\nNEWEST"

    def test_the_emitted_size_does_not_grow_with_the_source(self) -> None:
        """The whole point of a static marker: two sources of very different
        lengths must produce the same number of bytes, or the "cap" still moves
        the request size (and the cache boundary) turn to turn."""
        short = cap_section("a" * 500, 100, "…marker…")
        long = cap_section("a" * 50_000, 100, "…marker…")

        assert len(short) == len(long)


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
        """A user with no consolidated documents starts at a churning section.
        Requiring the blank line ahead of the heading filed that section as
        stable — putting per-turn bytes in the prefix for exactly those users."""
        before, body = _split_off_section(f"{AGENDA_HEADING}\n- ship it", AGENDA_HEADING)

        assert before == ""
        assert body == "\n- ship it"

    def test_an_absent_heading_leaves_the_core_whole(self) -> None:
        before, body = _split_off_section("Loves espresso.", AGENDA_HEADING)

        assert before == "Loves espresso."
        assert body == ""


@pytest.mark.unit
class TestTheMemoryCoreSplit:
    """``get_core_context`` renders documents, agenda and journal as one string.
    Only the documents are byte-stable; the other two are rewritten every turn,
    so they are two sections in two different slots.
    """

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
            f"{AGENDA_HEADING}\n- ship the cache work\n\n{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"
        )

    async def test_a_core_with_no_documents_still_yields_its_volatile_half(self) -> None:
        """The stable slot holds the documents or nothing. Filling it from
        "whatever came first" put a churning section in the cached prefix for
        every user who has not been consolidated yet."""
        with self._core(f"{RECENT_ACTIVITY_HEADING}\n- reviewed a PR"):
            assert await build_core_memory_block(ctx()) == ""
            assert "- reviewed a PR" in await build_agenda_and_activity_block(ctx())

    async def test_the_agenda_cap_does_not_swallow_the_journal(self) -> None:
        """The agenda's cap must bound the agenda ALONE. ``get_core_context``
        emits the agenda before the journal, so splitting on the agenda first
        hands back the journal with it; capping that blob discarded the agenda's
        commitments and relabelled the journal's tail as the agenda — invisible
        until the journal is long enough to blow the cap.
        """
        journal = "\n".join(f"- did thing {i}" for i in range(200))
        core = (
            "Loves espresso."
            f"\n\n{AGENDA_HEADING}\n- ship the cache work"
            f"\n\n{RECENT_ACTIVITY_HEADING}\n{journal}"
        )
        with self._core(core):
            block = await build_agenda_and_activity_block(ctx())

        agenda_block = block.split(RECENT_ACTIVITY_HEADING)[0]
        assert "- ship the cache work" in agenda_block
        assert block.count(RECENT_ACTIVITY_HEADING) == 1
        assert "- did thing 199" in block

    async def test_the_stable_documents_are_never_capped(self) -> None:
        """Truncating them would churn the cached prefix every time the core grew
        — the exact failure the split exists to prevent."""
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
        """No core document at all is not the same as an empty-looking one —
        both halves of the split come back empty rather than one manufacturing
        a header over nothing."""
        with self._core(""):
            assert await build_core_memory_block(ctx()) == ""
            assert await build_agenda_and_activity_block(ctx()) == ""

    async def test_each_oversized_section_is_labelled_by_its_own_marker(self) -> None:
        """An overflowing agenda and an overflowing journal each keep their own
        truncation marker. The markers are what tell the model its view of that
        section is partial, and they are byte-stable so an overflowing section
        emits the same prefix every turn."""
        agenda = "stale commitment. " * 40 + "A" * AGENDA_CAP_CHARS
        journal = "stale entry. " * 40 + "J" * RECENT_ACTIVITY_CAP_CHARS
        core = (
            f"Loves espresso.\n\n{AGENDA_HEADING}\n{agenda}\n\n{RECENT_ACTIVITY_HEADING}\n{journal}"
        )
        with self._core(core):
            block = await build_agenda_and_activity_block(ctx())

        assert block == (
            f"{AGENDA_HEADING}{AGENDA_TRUNC_MARKER}\n{'A' * AGENDA_CAP_CHARS}"
            f"\n\n{RECENT_ACTIVITY_HEADING}{RECENT_ACTIVITY_TRUNC_MARKER}"
            f"\n{'J' * RECENT_ACTIVITY_CAP_CHARS}"
        )


@pytest.mark.unit
class TestVolatileSectionCaps:
    """Every fetched volatile section is emitted verbatim until it outgrows its
    OWN budget, then keeps its newest bytes behind its own marker. Together these
    bound the per-turn block, which is what caps the achievable cache hit rate.
    """

    async def test_an_oversized_recall_keeps_its_newest_memories(self) -> None:
        memories = [memory("m" * 200, mentioned="2026-02-01") for _ in range(10)]
        with patch(
            "app.memory.engine.memory_engine.recall",
            AsyncMock(return_value=MemorySearchResult(memories=memories)),
        ):
            block = await build_memory_recall_block(ctx())

        body = block.removeprefix(f"{MEMORY_RECALL_HEADER}\n")
        assert body.startswith(MEMORIES_TRUNC_MARKER)
        assert len(body) == len(MEMORIES_TRUNC_MARKER) + 1 + MEMORIES_CAP_CHARS

    async def test_an_oversized_knowledge_block_keeps_its_own_budget(self) -> None:
        with patch(
            "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
            AsyncMock(return_value=[knowledge("k" * 400)]),
        ):
            block = await build_gaia_knowledge_block(ctx())

        body = block.removeprefix(f"{GAIA_KNOWLEDGE_HEADER}\n")
        assert body.startswith(GAIA_KNOWLEDGE_TRUNC_MARKER)
        assert len(body) == len(GAIA_KNOWLEDGE_TRUNC_MARKER) + 1 + GAIA_KNOWLEDGE_CAP_CHARS

    async def test_an_oversized_todo_summary_keeps_its_own_budget(self) -> None:
        with patch(
            "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
            AsyncMock(return_value="t" * 400),
        ):
            block = await build_tracked_todos_block(ctx(active_todo_id="todo-1"))

        assert block == f"{TRACKED_TODOS_TRUNC_MARKER}\n{'t' * TRACKED_TODOS_CAP_CHARS}"
