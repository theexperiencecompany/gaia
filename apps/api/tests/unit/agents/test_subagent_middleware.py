"""Tests for app/agents/middleware/subagent.py — SubagentMiddleware."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.tools import BaseTool
from langgraph.errors import GraphInterrupt
import pytest

MODULE = "app.agents.middleware.subagent"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware(**kwargs):
    """Create SubagentMiddleware with default test wiring."""
    from app.agents.middleware.subagent import SubagentMiddleware, SubagentMiddlewareConfig

    defaults = {
        "llm": None,
        "available_tools": [],
        "tool_registry": None,
        "max_turns": 5,
    }
    defaults.update(kwargs)
    return SubagentMiddleware(SubagentMiddlewareConfig(**defaults))


def _ready_middleware(**kwargs):
    """Middleware wired far enough to actually run a spawn."""
    mw = _make_middleware(llm=MagicMock(), spawn_middleware_factory=lambda space: [], **kwargs)
    mw.set_spawn_graph_provider(AsyncMock(return_value=MagicMock()))
    return mw


def _make_tool(name: str) -> MagicMock:
    """Create a mock BaseTool."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=f"{name} result")
    return tool


def _make_config(user_id: str = "u1") -> dict:
    return {"configurable": {"user_id": user_id}}


def _make_spawn_config(**configurable) -> dict:
    return {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-1",
            "email": "u1@example.com",
            "user_name": "Ada",
            **configurable,
        }
    }


def _paused(approval_id: str):
    from app.agents.core.subagents.subagent_runner import SubagentOutcome

    return SubagentOutcome(text="", interrupt={"approval_id": approval_id})


def _done(text: str):
    from app.agents.core.subagents.subagent_runner import SubagentOutcome

    return SubagentOutcome(text=text)


@contextmanager
def _spawn_harness(outcomes, decisions=("approved",), recovered=None):
    """Patch only the edges of a spawn: the LangGraph stream context, memory
    retrieval, the graph runner, and the HIL interrupt. Everything the
    middleware itself does (context building, the drive loop, event emission,
    exception routing) stays real.
    """
    writer = MagicMock()
    execute = AsyncMock(side_effect=outcomes)
    resume = MagicMock(side_effect=decisions)
    recover = AsyncMock(return_value=recovered)
    with (
        patch(f"{MODULE}.get_stream_writer", return_value=writer),
        patch(f"{MODULE}.build_initial_messages", new=AsyncMock(return_value=[])),
        patch(f"{MODULE}.execute_subagent_stream", new=execute),
        patch(f"{MODULE}.resume_for_gate", new=resume),
        patch(f"{MODULE}.recover_from_checkpoint", new=recover),
    ):
        yield SimpleNamespace(writer=writer, execute=execute, resume=resume, recover=recover)


@contextmanager
def _context_harness(spawn_configurable=None):
    """Capture what ``_build_context`` hands the two config builders.

    The fakes spell out the real keyword-only signatures rather than standing in
    as ``AsyncMock``: every field ``_build_context`` fills is a dataclass field
    with a default, so one that is dropped or nulled still builds a valid object
    and only shows up as the spawn running as the wrong user, on the parent's
    thread, or with the wrong turn limit.
    """
    captured = SimpleNamespace()
    captured.spawn_config = {"configurable": dict(spawn_configurable or {"user_id": "spawned-u1"})}

    async def build_agent_config(*, identity, lane=None, thread=None, turn=None, tracing=None):
        captured.identity = identity
        captured.lane = lane
        captured.thread = thread
        return captured.spawn_config

    async def build_initial_messages(*, system_message, agent_name, task, seed):
        captured.system_message = system_message
        captured.agent_name = agent_name
        captured.task = task
        captured.seed = seed
        return ["seeded"]

    with (
        patch(f"{MODULE}.build_agent_config", new=build_agent_config),
        patch(f"{MODULE}.build_initial_messages", new=build_initial_messages),
    ):
        yield captured


def _start_event(writer: MagicMock) -> dict:
    return next(
        c.args[0]["subagent_start"] for c in writer.call_args_list if "subagent_start" in c.args[0]
    )


def _event_names(writer: MagicMock) -> list[str]:
    return [next(iter(c.args[0])) for c in writer.call_args_list]


def _tool_message(command):
    return command.update["messages"][0]


# ---------------------------------------------------------------------------
# SubagentMiddleware.__init__
# ---------------------------------------------------------------------------


class TestSubagentMiddlewareInit:
    def test_default_init_builds_the_model_facing_spawn_tool(self):
        from app.agents.prompts.spawn_subagent_prompts import SPAWN_SUBAGENT_DESCRIPTION

        mw = _make_middleware()

        assert [t.name for t in mw.tools] == ["spawn_subagent"]
        spawn = mw.tools[0]
        assert spawn.description == SPAWN_SUBAGENT_DESCRIPTION
        # tool_call_id, selected_tool_ids and config are injected at runtime. If
        # they leak into the model-facing schema the LLM invents a tool_call_id
        # (breaking the row id and the resume checkpoint) and its own tool allowlist.
        assert set(spawn.tool_call_schema.model_json_schema()["properties"]) == {"task", "context"}
        assert "spawn_subagent" in mw._excluded_tools

    async def test_default_available_tools_yield_an_empty_spawn_registry(self):
        """``available_tools or []`` — dropping the fallback survives construction
        and only explodes mid-spawn, inside ``_build_context``'s comprehension.
        """
        mw = _ready_middleware(available_tools=None)

        with _spawn_harness(outcomes=[_done("ok")]):
            await mw.tools[0].coroutine(
                task="summarise",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(),
            )

        assert mw._spawn_graph_provider.await_args.kwargs["registry"] == {}

    def test_excluded_tools_include_spawn_subagent(self):
        mw = _make_middleware(excluded_tool_names={"some_tool"})
        assert "spawn_subagent" in mw._excluded_tools
        assert "some_tool" in mw._excluded_tools

    def test_custom_tool_runtime_config(self):
        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        config = ToolRuntimeConfig(
            initial_tool_names=["my_tool"],
            enable_retrieve_tools=False,
            include_subagents_in_retrieve=True,
        )
        mw = _make_middleware(tool_runtime_config=config)
        assert mw._tool_runtime_config.initial_tool_names == ["my_tool"]
        assert mw._tool_runtime_config.enable_retrieve_tools is False

    def test_the_configured_store_is_kept(self):
        """``set_store`` is the usual path, so a constructor that dropped the
        configured store would only be noticed by a caller that passes one."""
        store = MagicMock()

        assert _make_middleware(store=store)._store is store

    def test_default_tool_runtime_config(self):
        mw = _make_middleware()
        assert mw._tool_runtime_config.enable_retrieve_tools is True
        assert mw._tool_runtime_config.include_subagents_in_retrieve is False
        assert "read" in mw._tool_runtime_config.initial_tool_names


# ---------------------------------------------------------------------------
# set_llm / set_store / set_tools
# ---------------------------------------------------------------------------


class TestSetters:
    def test_set_llm(self):
        mw = _make_middleware()
        mock_llm = MagicMock()
        mock_llm.with_retry = MagicMock(return_value=mock_llm)
        mw.set_llm(mock_llm)
        assert mw._llm is mock_llm

    def test_set_store(self):
        mw = _make_middleware()
        mock_store = MagicMock()
        mw.set_store(mock_store)
        assert mw._store is mock_store

    def test_set_tools_updates_all(self):
        mw = _make_middleware()
        tools = [_make_tool("t1")]
        registry = {"r1": _make_tool("r1")}
        mw.set_tools(
            tools=tools,
            registry=registry,
            excluded_tool_names={"bad_tool"},
            tool_space="gmail",
        )
        assert mw._available_tools == tools
        assert mw._tool_registry == registry
        assert "bad_tool" in mw._excluded_tools
        assert "spawn_subagent" in mw._excluded_tools
        assert mw._tool_space == "gmail"

    def test_set_tools_partial(self):
        mw = _make_middleware()
        original_tools = mw._available_tools
        mw.set_tools(tool_space="slack")
        assert mw._tool_space == "slack"
        assert mw._available_tools is original_tools

    def test_set_tools_with_runtime_config(self):
        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        mw = _make_middleware()
        new_config = ToolRuntimeConfig(initial_tool_names=["x"], enable_retrieve_tools=False)
        mw.set_tools(tool_runtime_config=new_config)
        assert mw._tool_runtime_config is new_config


# ---------------------------------------------------------------------------
# spawn_subagent tool (integration-style)
# ---------------------------------------------------------------------------


class TestSpawnSubagentTool:
    def test_tool_created(self):
        mw = _make_middleware()
        assert len(mw.tools) == 1
        tool = mw.tools[0]
        assert tool.name == "spawn_subagent"

    async def test_missing_llm_returns_tool_error_without_spawning(self):
        mw = _make_middleware()
        provider = AsyncMock()
        mw.set_spawn_graph_provider(provider)

        result = await mw.tools[0].coroutine(
            task="summarise the file",
            tool_call_id="call_1",
            selected_tool_ids=[],
            config=_make_spawn_config(),
        )

        message = _tool_message(result)
        assert message.content == "Error: Subagent LLM not configured"
        assert message.status == "error"
        assert message.tool_call_id == "call_1"
        provider.assert_not_awaited()

    async def test_hil_pause_propagates_out_of_the_tool(self):
        """A GraphBubbleUp is the user's approval request in flight. Swallowing it
        into a tool error would drop the approval and silently finish the turn.
        """
        mw = _ready_middleware()
        with _spawn_harness(
            outcomes=[_paused("approval-1")],
            decisions=[GraphInterrupt()],
        ) as h:
            with pytest.raises(GraphInterrupt):
                await mw.tools[0].coroutine(
                    task="delete the repo",
                    tool_call_id="call_1",
                    selected_tool_ids=[],
                    config=_make_spawn_config(),
                )

        assert h.resume.call_args_list == [call({"approval_id": "approval-1"})]
        # The row stays live across the pause — ending it here would orphan the
        # spinner and open a duplicate when the approval resumes the spawn.
        assert _event_names(h.writer) == ["subagent_start"]

    async def test_unexpected_failure_becomes_a_tool_error(self):
        mw = _ready_middleware()
        with _spawn_harness(outcomes=[RuntimeError("chroma down")]) as h:
            result = await mw.tools[0].coroutine(
                task="summarise the file",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(),
            )

        message = _tool_message(result)
        assert message.content == "Subagent error: chroma down"
        assert message.status == "error"
        # A failed spawn must close its row, or the UI spins forever.
        assert _event_names(h.writer) == ["subagent_start", "subagent_end"]

    async def test_drive_resumes_every_gate_before_returning(self):
        """Two gated calls in one task pause twice; each resume carries its own
        gate's decision and only the final, unpaused outcome is the tool result.
        """
        mw = _ready_middleware()
        with _spawn_harness(
            outcomes=[_paused("approval-1"), _paused("approval-2"), _done("deleted 2 files")],
            decisions=["approve-1", "approve-2"],
        ) as h:
            result = await mw.tools[0].coroutine(
                task="clean up",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(),
            )

        assert _tool_message(result).content == "deleted 2 files"
        assert h.execute.await_count == 3
        assert h.resume.call_args_list == [
            call({"approval_id": "approval-1"}),
            call({"approval_id": "approval-2"}),
        ]
        resumed = [c.kwargs.get("resume") for c in h.execute.await_args_list]
        assert resumed[0] is None
        assert [r.resume for r in resumed[1:]] == ["approve-1", "approve-2"]
        assert _event_names(h.writer) == ["subagent_start", "subagent_end"]

    async def test_fresh_spawn_never_probes_the_checkpoint(self):
        mw = _ready_middleware()
        with _spawn_harness(outcomes=[_done("ok")]) as h:
            await mw.tools[0].coroutine(
                task="summarise",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(),
            )

        h.recover.assert_not_awaited()
        assert h.execute.await_count == 1

    async def test_replay_returns_the_checkpointed_result_without_rerunning(self):
        """A sibling's pause replays this tool node. Re-running the spawn would
        repeat every action it already took.
        """
        from app.constants.hil import HIL_RESUME_CONFIG_KEY

        mw = _ready_middleware()
        with _spawn_harness(outcomes=[_done("second run")], recovered=_done("first run")) as h:
            result = await mw.tools[0].coroutine(
                task="send the email",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(**{HIL_RESUME_CONFIG_KEY: True}),
            )

        assert _tool_message(result).content == "first run"
        h.recover.assert_awaited_once()
        h.execute.assert_not_awaited()

    async def test_spawn_context_isolates_the_thread_and_drops_excluded_tools(self):
        mw = _ready_middleware(excluded_tool_names={"handoff"})
        with _spawn_harness(outcomes=[_done("ok")]) as h:
            await mw.tools[0].coroutine(
                task="summarise",
                tool_call_id="call_abc",
                selected_tool_ids=["read", "handoff", "spawn_subagent"],
                config=_make_spawn_config(conversation_id="conv-9"),
            )

        ctx = h.execute.await_args.kwargs["ctx"]
        assert ctx.config["configurable"]["thread_id"] == "spawn_conv-9_call_abc"
        assert ctx.initial_state["selected_tool_ids"] == ["read"]


# ---------------------------------------------------------------------------
# Nesting: which row a spawned subagent renders inside
# ---------------------------------------------------------------------------


class TestSpawnNesting:
    """A spawn inherits its parent's row id so the UI can nest it.

    ``subagent_start`` carries ``parent_subagent_id``, read straight off the
    running config. The client builds its subagent tree from that field alone
    (``stream_utils.reconstruct_subagent_groups``), so a spawn that loses it does
    not render in the wrong place — it renders at the top level, as a sibling of
    the very subagent that started it.
    """

    async def test_a_spawn_inside_a_subagent_is_nested_under_it(self):
        mw = _ready_middleware()
        with _spawn_harness(outcomes=[_done("done")]) as h:
            await mw.tools[0].coroutine(
                task="read the attachment",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(subagent_id="parent-row-1"),
            )

        assert _start_event(h.writer)["parent_subagent_id"] == "parent-row-1"

    async def test_a_spawn_from_the_executor_has_no_parent(self):
        """The executor is not a subagent and owns no row, so its spawns belong
        at the top level. A fabricated parent id would target a group that does
        not exist and the row would be dropped."""
        mw = _ready_middleware()
        with _spawn_harness(outcomes=[_done("done")]) as h:
            await mw.tools[0].coroutine(
                task="read the attachment",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(),
            )

        assert "parent_subagent_id" not in _start_event(h.writer)

    async def test_a_spawn_gets_its_own_row_distinct_from_its_parent(self):
        mw = _ready_middleware()
        with _spawn_harness(outcomes=[_done("done")]) as h:
            await mw.tools[0].coroutine(
                task="read the attachment",
                tool_call_id="call_1",
                selected_tool_ids=[],
                config=_make_spawn_config(subagent_id="parent-row-1"),
            )

        event = _start_event(h.writer)
        assert event["subagent_id"] != event["parent_subagent_id"]
        assert event["agent_type"] == "spawned"

    async def test_the_row_id_is_stable_across_replays_of_one_call(self):
        """An approval pause replays the spawn. A fresh row id each time would
        orphan the paused row and open a duplicate on resume."""
        mw = _ready_middleware()
        ids = []
        for _ in range(2):
            with _spawn_harness(outcomes=[_done("done")]) as h:
                await mw.tools[0].coroutine(
                    task="read the attachment",
                    tool_call_id="call_same",
                    selected_tool_ids=[],
                    config=_make_spawn_config(subagent_id="parent-row-1"),
                )
            ids.append(_start_event(h.writer)["subagent_id"])

        assert ids[0] == ids[1]


# ---------------------------------------------------------------------------
# _build_context: what the spawn's own run config is built from
# ---------------------------------------------------------------------------


class TestBuildContextWiring:
    """The single seam where the parent run crosses into the spawn.

    Identity, thread and retrieval inputs are all passed by keyword into frozen
    dataclasses whose every field has a default, so a dropped or nulled one
    builds a perfectly valid object: the spawn just runs as nobody, on the
    parent's own thread, or with the comms turn limit instead of its own. The
    three objects are therefore pinned whole rather than field by field.
    """

    TASK = "summarise the attachment"

    async def _build(self, mw):
        return await mw._build_context(
            self.TASK, "", _make_spawn_config(conversation_id="conv-9"), "call_abc", []
        )

    async def test_the_spawn_runs_as_the_parents_user_in_the_parents_conversation(self):
        from app.constants.general import SPAWN_AGENT_NAME
        from app.helpers.agent_helpers import AgentIdentity

        mw = _ready_middleware()
        with _context_harness() as h:
            await self._build(mw)

        assert h.identity == AgentIdentity(
            conversation_id="conv-9",
            user={"user_id": "u1", "email": "u1@example.com", "name": "Ada"},
            agent_name=SPAWN_AGENT_NAME,
        )

    async def test_the_spawn_gets_its_own_thread_and_its_own_turn_limit(self):
        """``max_turns`` is the spawn loop's budget and the thread id is what
        keeps a resumed spawn finding its own checkpoint rather than the
        parent's. Both silently fall back to a working default when dropped.
        """
        from app.constants.general import SPAWN_AGENT_NAME
        from app.helpers.agent_helpers import AgentThread

        mw = _ready_middleware(max_turns=7)
        config = _make_spawn_config(conversation_id="conv-9")
        with _context_harness() as h:
            await mw._build_context(self.TASK, "", config, "call_abc", [])

        assert h.thread == AgentThread(
            thread_id="spawn_conv-9_call_abc",
            base_configurable=config["configurable"],
            subagent_id=SPAWN_AGENT_NAME,
            recursion_limit=7,
        )

    async def test_the_thread_seed_retrieves_against_the_spawns_own_run(self):
        """The seed decides which context sections the opening thread gets. It
        must read the SPAWN's configurable (the one just built), not the
        parent's, and retrieve against the task rather than nothing.
        """
        from app.agents.context.tiers import AgentTier
        from app.agents.core.subagents.subagent_runner import ThreadSeed

        mw = _ready_middleware()
        with _context_harness() as h:
            await self._build(mw)

        assert h.seed == ThreadSeed(
            tier=AgentTier.SPAWN,
            configurable=h.spawn_config["configurable"],
            user_id="u1",
            retrieval_query=self.TASK,
        )


class TestSpawnStartEvent:
    async def test_the_start_event_is_pinned_whole(self):
        """The client renders the row from this payload alone. ``tool_category``
        is what marks it a spawn rather than a handoff, and it drops out of the
        payload entirely when nulled (``exclude_none``), so a substring or
        key-by-key check would not see it go.
        """
        from app.agents.core.subagents.subagent_runner import subagent_row_id

        mw = _ready_middleware()
        with _spawn_harness(outcomes=[_done("ok")]) as h:
            await mw._run_spawn(
                task="summarise the attachment",
                context="",
                config=_make_spawn_config(subagent_id="parent-row-1"),
                tool_call_id="call_abc",
                inherited_tool_names=[],
            )

        event = _start_event(h.writer)
        assert {k: v for k, v in event.items() if k != "started_at"} == {
            "subagent_id": subagent_row_id("call_abc"),
            "subagent_name": "summarise the attachment",
            "agent_type": "spawned",
            "tool_category": "spawn_subagent",
            "parent_subagent_id": "parent-row-1",
        }
