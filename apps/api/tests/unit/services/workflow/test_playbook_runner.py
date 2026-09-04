"""Replaying a playbook: what actually runs, what is refused, and what it costs.

The runner's whole value is that it is cheaper than the agent and still safe, so
the tests defend both halves. Safety is not asserted against a stubbed gate: the
steps go through the REAL graph, the real middleware chain and the real HIL gate,
which is the only way to tell that a replay still gates every call now that the
runner no longer calls the gate itself.

A replay makes one model call when the playbook has no asks (the end-of-run
result and verdict), plus one ask fill for each step that carries ``$ask`` slots,
made immediately before that step so the slots are written from what has actually
run. The scripted model's turns are not model calls and never reach a provider.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Annotated, Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer
from langgraph.types import Command
from pydantic import ValidationError
import pytest

from app.agents.middleware.factory import (
    AccountingOptions,
    ContextOptions,
    SubagentStackOptions,
    create_middleware_stack as real_create_middleware_stack,
)
from app.agents.workspace.offload import mark_offload
from app.constants.hil import HIL_STATUS_KWARG
from app.constants.log_tags import LogTag
from app.models.playbook_models import (
    DEFAULT_ASK_MAX_TOKENS,
    PlaybookDocument,
    PlaybookStep,
)
from app.models.workflow_execution_models import (
    RECORD_CUT_MARKER,
    RESULT_DIGEST_MAX_CHARS,
    RecordedCall,
    build_result_digest,
)
from app.override.langgraph_bigtool.create_agent import create_agent as real_create_agent
from app.services.hil.prompts import UNPAUSABLE_DENIAL_TEMPLATE
from app.services.workflow.playbook.evaluator import PlaybookUser, RunContext
from app.services.workflow.playbook.runner import (
    PlaybookAskAnswer,
    PlaybookAskFill,
    PlaybookNarration,
    PlaybookRunResult,
    _fill_asks,
    _narrate,
    _render_asks,
    _Run,
    _run_handoff,
    _run_tool_step,
    _suspect_verdict,
    run_playbook,
)
from app.services.workflow.playbook.scripted_model import (
    REPLAY_FINISHED_CONTENT,
    ScriptedCall,
    ScriptedModel,
    scripted_call_id,
)
from app.services.workflow.playbook.tool_space import ToolSpace
from app.utils.chat_utils import get_user_id_from_config
from app.utils.timezone import Timezone

MODULE = "app.services.workflow.playbook.runner"
#: A handoff resolves its subagent inside tool_space, not the runner, so that is
#: where the lookup is stubbed. Everything below it (the scoped tool dict) runs
#: for real against the fake registry.
TOOL_SPACE_MODULE = "app.services.workflow.playbook.tool_space"
GATE = "app.services.hil.gate"

USER = PlaybookUser(email="ada@example.com", name="Ada", timezone="Europe/Berlin")


class _Recorder:
    """Collects the calls the tools actually received, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []


def _tools(
    recorder: _Recorder, *, failing: str | None = None, events_result: str = '{"count": 12}'
) -> dict[str, BaseTool]:
    @tool
    async def list_events(calendar_id: Annotated[str, "Calendar"], config: RunnableConfig) -> str:
        """List calendar events."""
        # Both reads are the point: a tool inside a graph resolves its user
        # through metadata and streams through the pregel runtime, and a replay
        # that supplies neither comes back with an error string that looks like
        # a result. Calling them here makes that a failure, not a silent empty.
        get_stream_writer()({"progress": "listing"})
        recorder.calls.append(
            (
                "list_events",
                {
                    "calendar_id": calendar_id,
                    "user": get_user_id_from_config(config),
                    # Which scope the call ran under: a handoff's children must
                    # reach the tool tagged as that subagent, and a top-level
                    # step must not be tagged at all.
                    "subagent": (config.get("configurable") or {}).get("subagent_id"),
                },
            )
        )
        if failing == "list_events":
            raise ValueError("calendar unavailable")
        return events_result

    @tool
    async def send_email(to: Annotated[str, "Recipient"], body: Annotated[str, "Body"] = "") -> str:
        """Send an email."""
        recorder.calls.append(("send_email", {"to": to, "body": body}))
        if failing == "send_email":
            raise ValueError("rejected argument 'body'")
        return "sent"

    @tool
    async def file_notes(items: Annotated[list[str], "Notes"]) -> str:
        """File a list of notes."""
        recorder.calls.append(("file_notes", {"items": items}))
        return "filed"

    return {"list_events": list_events, "send_email": send_email, "file_notes": file_notes}


class _FakeCategoryTool:
    def __init__(self, tool_obj: BaseTool) -> None:
        self.name = tool_obj.name
        self.tool = tool_obj


class _FakeCategory:
    def __init__(self, space: str, tools: list[BaseTool]) -> None:
        self.space = space
        self.tools = [_FakeCategoryTool(t) for t in tools]


class _FakeRegistry:
    """The tool registry seam: the runner reads tools from it, never builds them."""

    def __init__(self, tools: dict[str, BaseTool], spaces: dict[str, list[str]] | None = None):
        self._tools = tools
        self._spaces = spaces or {}

    def get_tool_dict(self) -> dict[str, BaseTool]:
        return self._tools

    def get_category_of_tool(self, tool_name: str) -> str:
        return "calendar" if tool_name == "list_events" else "mail"

    def get_category_by_space(self, space: str) -> _FakeCategory | None:
        names = self._spaces.get(space)
        if names is None:
            return None
        return _FakeCategory(space, [self._tools[name] for name in names])


class _FakeSubagentConfig:
    tool_space = "calendar"
    include_finish_task = False
    auto_bind_tools: ClassVar[list[str]] = []
    use_direct_tools = True
    disable_retrieve_tools = True


class _FakeSubagent:
    id = "calendar_agent"
    managed_by = "internal"
    mcp_config = None
    config = _FakeSubagentConfig()


def _playbook(steps: list[PlaybookStep]) -> PlaybookDocument:
    return PlaybookDocument(
        description="Mail the day's agenda",
        steps=steps,
        result_brief="Say how many events there were and that the mail went out.",
        workflow_id="wf_1",
        user_id="u_1",
        workflow_hash="hash_1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _narration(result: str = "Twelve events, mail sent.") -> PlaybookNarration:
    return PlaybookNarration(result=result)


def _slot(prompt: str, max_tokens: int | None = None) -> dict[str, Any]:
    """An ask slot as it is authored: the instruction, standing in the argument.

    Written as a plain dict rather than through ``AskSlot`` because that is what
    a stored playbook holds and what the runner has to recognise.
    """
    slot: dict[str, Any] = {"$ask": prompt}
    if max_tokens is not None:
        slot["max_tokens"] = max_tokens
    return slot


def _ask_fill(asks: dict[str, str] | None = None) -> PlaybookAskFill:
    """What one ask call answers, keyed by each slot's ``<step>.<arg>`` key."""
    return PlaybookAskFill(
        asks=[PlaybookAskAnswer(name=name, text=text) for name, text in (asks or {}).items()]
    )


def _ask_prompt(llm: AsyncMock, index: int = 0) -> str:
    """The prompt an ask call was given; the ask calls come before the end-of-run one."""
    return str(llm.await_args_list[index].args[1])


def _result_prompt(llm: AsyncMock) -> str:
    """The prompt the end-of-run call was given: always the LAST model call."""
    return str(llm.await_args.args[1])


@contextmanager
def _gate_policy(policy: str) -> Iterator[AsyncMock]:
    """Run the REAL HIL gate with only its preference lookup replaced.

    ``resolve_policy`` is the gate's one I/O dependency (the user's HIL
    preferences and the tool's destructive classification). Everything after it
    — the pausability check, the refusal message, the fail-closed behaviour of a
    background run — is the production gate.
    """
    resolve = AsyncMock(return_value=policy)
    with patch(f"{GATE}.resolve_policy", resolve):
        yield resolve


@dataclass(frozen=True)
class _Seams:
    """The mocked seams a test may hold on to; see ``_run``."""

    subagent: _FakeSubagent | None = None
    runnable: MagicMock | None = None
    find_previous: AsyncMock | None = None
    llm: AsyncMock | None = None


async def _run(
    playbook: PlaybookDocument,
    registry: _FakeRegistry,
    narration: PlaybookNarration | None = None,
    ask_fill: PlaybookAskFill | None = None,
    policy: str = "allow",
    seams: _Seams | None = None,
) -> tuple[PlaybookRunResult, AsyncMock]:
    """Run the playbook with mocked seams; hands back the result and the LLM mock.

    ``narration`` is what the end-of-run call returns; ``ask_fill`` is what the
    ask call returns, and giving one makes the model answer the ask call first
    and the narration second, in that order — so it fits a playbook whose slots
    all sit on one step. A playbook with slots on several steps makes an ask
    call per step and scripts them through ``seams.llm`` instead. ``runnable``,
    ``find_previous`` and ``llm`` let a test hold on to the seam it is asserting
    about: how a model call is built, what the previous execution's trace was
    looked up with, and what the model calls do.
    """
    seams = seams or _Seams()
    subagent, runnable, find_previous, llm = (
        seams.subagent,
        seams.runnable,
        seams.find_previous,
        seams.llm,
    )
    if llm is None:
        llm = (
            AsyncMock(side_effect=[ask_fill, narration or _narration()])
            if ask_fill is not None
            else AsyncMock(return_value=narration or _narration())
        )
    with (
        patch(f"{MODULE}.get_tool_registry", AsyncMock(return_value=registry)),
        patch(
            f"{MODULE}.workflow_executions_repository.find_latest_with_trace",
            find_previous or AsyncMock(return_value=None),
        ),
        # Keyed on the id, so a lookup that drops the handoff target resolves to
        # nothing instead of quietly answering with the only subagent around.
        patch(
            f"{TOOL_SPACE_MODULE}.get_subagent_by_id",
            lambda subagent_id: subagent
            if subagent is not None and subagent_id == subagent.id
            else None,
        ),
        # The model calls run on whatever provider the deployment uses, so the
        # runnable is built then invoked. Both halves are stubbed: the test cares
        # how many model calls happen and what they return, not which lane served them.
        patch(f"{MODULE}.background_structured_runnable", runnable or MagicMock()),
        patch(f"{MODULE}.ainvoke_llm", llm),
        _gate_policy(policy),
    ):
        result = await run_playbook(
            playbook, user=USER, conversation_id="conv_1", trigger={"to": "team@example.com"}
        )
    return result, llm


AGENDA_STEPS = [
    PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
    PlaybookStep(id="mail", tool="send_email", args={"to": "$trigger.to"}),
]


# --- the scripted model ----------------------------------------------------


def test_the_scripted_model_emits_its_calls_in_order_then_ends_the_loop() -> None:
    model = ScriptedModel(
        script=[
            ScriptedCall(name="list_events", args={"calendar_id": "primary"}),
            ScriptedCall(name="send_email", args={"to": "team@example.com"}),
        ]
    )
    conversation: list[Any] = [HumanMessage(content="go")]
    emitted: list[Any] = []

    for _ in range(3):
        message = model.turn_for(conversation)
        emitted.append(message)
        conversation.append(message)
        for call in message.tool_calls:
            conversation.append(
                ToolMessage(content="ok", tool_call_id=call["id"], name=call["name"])
            )

    assert [call["name"] for message in emitted for call in message.tool_calls] == [
        "list_events",
        "send_email",
    ]
    assert emitted[0].tool_calls[0]["args"] == {"calendar_id": "primary"}
    # The turn after the last scripted call carries no tool calls, which is the
    # only thing that lets the agent loop terminate.
    assert emitted[2].tool_calls == []
    assert emitted[2].content == REPLAY_FINISHED_CONTENT


def test_the_scripted_model_reads_its_position_off_the_messages() -> None:
    """A retried or replayed superstep re-emits the same call, never the next one."""
    model = ScriptedModel(
        script=[
            ScriptedCall(name="list_events", args={"calendar_id": "primary"}),
            ScriptedCall(name="send_email", args={"to": "team@example.com"}),
        ]
    )
    conversation = [HumanMessage(content="go")]

    first = model.turn_for(conversation)
    again = model.turn_for(conversation)

    assert first.tool_calls == again.tool_calls
    assert first.tool_calls[0]["id"] == scripted_call_id(0)


# --- a replay through the real graph ---------------------------------------


async def test_steps_run_in_order_through_the_registry() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is True, result.failure
    assert [name for name, _ in recorder.calls] == ["list_events", "send_email"]
    assert [call.tool_name for call in result.trace] == ["list_events", "send_email"]


async def test_resolved_arguments_reach_the_tool() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    await _run(_playbook(AGENDA_STEPS), registry)

    assert recorder.calls[1][1]["to"] == "team@example.com"


async def test_a_replayed_tool_resolves_the_run_user() -> None:
    """Regression: the runner used to hand-build the tool config and got it wrong.

    A replayed ``list_todos`` came back "User authentication required" with zero
    items while the agent path returned 38, because ``get_user_id_from_config``
    reads ``config["metadata"]`` and only ``configurable`` was set. The graph is
    what copies one into the other, so running inside one is the fix.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is True, result.failure
    assert recorder.calls[0][1]["user"] == "u_1"


async def test_a_gated_call_is_refused_without_invoking_the_tool() -> None:
    """The real gate, in the real graph: a background run cannot ask, so it refuses."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry, policy="ask")

    assert recorder.calls == []
    assert result.ok is False
    assert "list_events" in (result.failure or "")
    assert "approval gate" in (result.failure or "")
    # The gate's own words, not the runner's: proof the refusal came from
    # production HIL inside the graph rather than from a check the runner kept.
    assert UNPAUSABLE_DENIAL_TEMPLATE.format(tool="list_events") in (result.failure or "")
    # Nothing was attempted, so nothing may reach the trace the next run reads.
    assert result.trace == []


async def test_one_ask_call_covers_two_asks_and_one_result_call_follows() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={
                    "to": _slot("Who should get this?"),
                    "body": _slot("Write the digest."),
                },
            ),
        ]
    )
    ask_fill = _ask_fill({"mail.to": "team@example.com", "mail.body": "Twelve events today."})

    result, llm = await _run(playbook, registry, ask_fill=ask_fill)

    assert llm.await_count == 2
    assert result.ok is True, result.failure
    assert recorder.calls[1][1] == {"to": "team@example.com", "body": "Twelve events today."}
    assert result.text == "Twelve events, mail sent."
    assert result.llm_calls == 2
    # Both fields reach the end call as separate lines: run together they read
    # as one field whose text is the other's, which is what it writes from.
    assert _prompt_block(_result_prompt(llm), "asks") == (
        "- mail.to: team@example.com\n- mail.body: Twelve events today."
    )


async def test_a_playbook_with_no_slots_makes_exactly_one_model_call() -> None:
    """A playbook with nothing to write pays for the narration and nothing else.

    The ask fill is the replay's one optional cost. A second call on a playbook
    that has no slot to fill is a model call bought for nothing, on every fire
    of every workflow that never needed one.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, llm = await _run(_playbook(AGENDA_STEPS), registry)

    assert llm.await_count == 1
    assert result.llm_calls == 1


async def test_a_run_that_stops_before_any_ask_makes_no_model_call() -> None:
    """Two scripted turns per step and still zero real calls when the run stops early."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="list_events"))

    result, llm = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is False
    assert llm.await_count == 0
    assert result.llm_calls == 0


async def test_a_failing_step_stops_the_run_and_names_the_step_and_tool() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="send_email"))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is False
    failure = result.failure or ""
    assert "step 2" in failure
    assert "send_email" in failure
    assert "rejected argument 'body'" in failure
    assert result.text == ""


async def test_a_failing_step_leaves_the_earlier_calls_on_the_trace() -> None:
    """A run that dies after a side effect still records what already happened."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="send_email"))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert [call.tool_name for call in result.trace] == ["list_events", "send_email"]
    assert result.trace[0].result_digest == '{"count": 12}'
    assert result.completed == ['events (list_events {"calendar_id":"primary"}) -> {"count": 12}']


async def test_the_failure_names_what_already_completed() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="send_email"))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert "events (list_events " in (result.failure or "")


async def test_a_step_whose_placeholder_is_stale_stops_the_run() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [PlaybookStep(id="mail", tool="send_email", args={"to": "$steps.gone.address"})]
    )

    result, _ = await _run(playbook, registry)

    assert result.ok is False
    assert "$steps.gone.address" in (result.failure or "")
    assert recorder.calls == []


async def test_a_tool_outside_the_registry_stops_the_run() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook([PlaybookStep(id="x", tool="NOT_A_TOOL", args={})])

    result, _ = await _run(playbook, registry)

    assert result.ok is False
    assert "NOT_A_TOOL" in (result.failure or "")


async def test_a_step_result_is_addressable_by_the_next_step() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": "Found $steps.events.count events"},
            ),
        ]
    )

    await _run(playbook, registry)

    assert recorder.calls[1][1]["body"] == "Found 12 events"


# --- handoffs --------------------------------------------------------------

HANDOFF_PLAYBOOK = [
    PlaybookStep(
        handoff="calendar_agent",
        steps=[PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"})],
    )
]


async def test_a_handoff_child_runs_in_the_subagents_scoped_tool_space() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})

    result, _ = await _run(
        _playbook(HANDOFF_PLAYBOOK), registry, seams=_Seams(subagent=_FakeSubagent())
    )

    assert result.ok is True, result.failure
    assert [name for name, _ in recorder.calls] == ["list_events"]
    assert [call.tool_name for call in result.trace] == ["handoff", "list_events"]
    assert result.trace[1].subagent_id == "calendar_agent"


async def test_a_handoff_child_calling_a_tool_outside_that_scope_fails_the_step() -> None:
    """``send_email`` exists at top level and is not in the calendar subagent's space."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
    playbook = _playbook(
        [
            PlaybookStep(
                handoff="calendar_agent",
                steps=[PlaybookStep(id="mail", tool="send_email", args={"to": "x@example.com"})],
            )
        ]
    )

    result, _ = await _run(playbook, registry, seams=_Seams(subagent=_FakeSubagent()))

    assert result.ok is False
    assert recorder.calls == []
    assert "send_email" in (result.failure or "")
    assert [call.tool_name for call in result.trace] == ["handoff"]


async def test_an_unknown_handoff_target_stops_the_run() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, seams=_Seams(subagent=None))

    assert result.ok is False
    assert "calendar_agent" in (result.failure or "")
    assert recorder.calls == []


class _FakeMcpSubagent(_FakeSubagent):
    """The calendar subagent as an MCP integration: its live tools come from the
    user's client and are nowhere in the registry's category."""

    managed_by = "mcp"
    mcp_config = object()


async def test_a_handoff_child_may_run_a_tool_the_users_mcp_client_provides() -> None:
    """The validator accepted this step because the MCP tool is in the space.
    The replay then refused it as "outside the bound tool set" because the ids
    the handoff bound were only the registry ones — the same step, accepted at
    write time and rejected at run time."""
    recorder = _Recorder()
    tools = _tools(recorder)
    registry = _FakeRegistry(tools, spaces={"calendar": ["list_events"]})
    playbook = _playbook(
        [
            PlaybookStep(
                handoff="calendar_agent",
                steps=[PlaybookStep(id="mail", tool="send_email", args={"to": "x@example.com"})],
            )
        ]
    )

    connected_as: list[str] = []

    async def mcp_client(user_id: str) -> MagicMock:
        connected_as.append(user_id)
        client = MagicMock()
        client.ensure_connected = AsyncMock(return_value=[tools["send_email"]])
        return client

    with patch(f"{TOOL_SPACE_MODULE}.get_mcp_client", mcp_client):
        result, _ = await _run(playbook, registry, seams=_Seams(subagent=_FakeMcpSubagent()))

    assert result.ok is True, result.failure
    assert [name for name, _ in recorder.calls] == ["send_email"]
    assert [call.tool_name for call in result.trace] == ["handoff", "send_email"]
    # An MCP subagent's tools live on the OWNER's client, so the playbook's user
    # is what the handoff resolves against: anyone else's client answers with a
    # different tool set, or with none, and the recorded step is refused.
    assert connected_as == ["u_1"]


# --- a step or the narration that raises ------------------------------------


async def test_a_step_that_raises_stops_the_run_with_the_completed_steps_on_record() -> None:
    """An exception out of the step's graph used to escape ``run_playbook``
    before any result existed, so the worker never saw ``ok=False`` and the
    trace of the steps that had already run — with their side effects — was
    lost with it."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    def exploding_agent(llm: Any, *args: Any, **kwargs: Any) -> Any:
        if llm.script[0].name == "send_email":
            raise RuntimeError("graph exploded")
        return real_create_agent(llm, *args, **kwargs)

    with patch(f"{MODULE}.create_agent", exploding_agent):
        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is False
    assert [call.tool_name for call in result.trace] == ["list_events"]
    assert result.completed == ['events (list_events {"calendar_id":"primary"}) -> {"count": 12}']
    assert result.failure is not None
    assert result.failure.startswith("Playbook stopped at step 2 (send_email): ")
    assert "RuntimeError" in result.failure
    assert "graph exploded" in result.failure
    assert "events (list_events " in result.failure


async def test_a_step_that_raises_is_logged_with_its_error_type() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(AGENDA_STEPS)

    def exploding_agent(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("graph exploded")

    with patch(f"{MODULE}.create_agent", exploding_agent), patch(f"{MODULE}.log") as log:
        await _run(playbook, registry)

    assert log.exception.call_count == 1
    # The whole event, not a field of it: the message is what a reader searches
    # for, and each id is what joins this line to the workflow it broke. A line
    # missing one of them is a raise nobody can attribute afterwards.
    assert log.exception.call_args.args == (
        f"{LogTag.WORKFLOW} Playbook step raised instead of returning a result",
    )
    assert log.exception.call_args.kwargs == {
        "playbook_id": playbook.playbook_id,
        "workflow_id": "wf_1",
        "tool_name": "list_events",
        "error_type": "RuntimeError",
    }


async def test_a_narration_that_raises_after_every_step_is_still_a_completed_run() -> None:
    """The steps ARE the workflow; the narration is the sentence about them.

    Prod: 13 of 15 failed replays had every tool step complete and only this
    call raise. Reported as a stopped run, the user got nothing and the next
    fire spent a full heal run on a sequence that had just worked. A run that
    ran everything is a run that finished, and it delivers what it did.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(AGENDA_STEPS)

    with patch(f"{MODULE}.log") as log:
        result, _ = await _run(
            playbook,
            registry,
            seams=_Seams(llm=AsyncMock(side_effect=TimeoutError("model"))),
        )

    assert result.ok is True
    assert result.failure is None
    assert [call.tool_name for call in result.trace] == ["list_events", "send_email"]
    assert result.narration_failed == "the narration raised TimeoutError: model"
    # The delivered text has to stand in for the summary nobody wrote: why it is
    # missing, and every step that ran, so the user is not told a blank page.
    assert result.narration_failed in result.text
    for line in result.completed:
        assert f"- {line}" in result.text
    assert len(result.completed) == 2
    # No verdict was written, so there is none to report: the narration is what
    # judges a run, and it never spoke.
    assert result.suspect is None
    assert result.suspect_source is None
    assert result.llm_calls == 0
    # The call still died, and the fleet still hears about it — the run being
    # deliverable is not the same as the model call being fine.
    assert log.exception.call_args.args == (f"{LogTag.WORKFLOW} Playbook model call raised",)
    assert log.exception.call_args.kwargs == {
        "playbook_id": playbook.playbook_id,
        "workflow_id": "wf_1",
        "call": "narration",
        "error_type": "TimeoutError",
    }


async def test_a_narration_failure_still_counts_the_ask_call_that_did_return() -> None:
    """``llm_calls`` is the replay's cost line: the ask fill was billed, the
    narration that raised was not."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": _slot("Write the body")},
            ),
        ]
    )

    result, _ = await _run(
        playbook,
        registry,
        seams=_Seams(
            llm=AsyncMock(
                side_effect=[_ask_fill({"mail.body": "Here it is."}), RuntimeError("boom")]
            )
        ),
    )

    assert result.ok is True
    assert result.narration_failed == "the narration raised RuntimeError: boom"
    assert result.llm_calls == 1


async def test_a_mid_run_ask_fill_that_raises_stops_before_the_step_that_needed_it() -> None:
    """A step addressing ``$ask`` triggers the ask fill first. If that raises,
    the step must not run with the ask unfilled, and no result call follows."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": _slot("Write the body")},
            ),
        ]
    )

    result, _ = await _run(
        playbook, registry, seams=_Seams(llm=AsyncMock(side_effect=TimeoutError("model")))
    )

    assert result.ok is False
    assert [name for name, _ in recorder.calls] == ["list_events"]
    assert [call.tool_name for call in result.trace] == ["list_events"]
    assert result.failure is not None
    # The exception itself, not just its label: the agent picking this fire up
    # is told what died, and "raised NoneType: None" tells it nothing.
    assert result.failure.startswith(
        "Playbook stopped at step 2 (ask_fill): the ask_fill raised TimeoutError: model."
    )
    assert result.llm_calls == 0


def test_the_scripted_model_never_reaches_a_provider() -> None:
    """It answers from the messages alone — no client, no key, no token spend."""
    model = ScriptedModel(script=[ScriptedCall(name="list_events", args={})])

    assert isinstance(model.turn_for([]), AIMessage)
    assert model._llm_type == "playbook-scripted"


async def test_the_narration_sees_the_whole_result_not_a_snippet_of_it() -> None:
    """The narration writes the user's result, so it must see the actual data.

    Regression: the failure report and the narration prompt shared one 120-char
    bound. A list result reached the model cut mid-token, so it described the run
    as truncated and reported one item out of many. It was summarising the bound
    rather than the data, and the run looked broken to the user while every tool
    call had in fact succeeded.
    """
    payload = json.dumps({"todos": [{"title": f"Todo {i}"} for i in range(30)]})
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, events_result=payload))
    playbook = _playbook(
        [PlaybookStep(id="all", tool="list_events", args={"calendar_id": "primary"})]
    )

    result, llm = await _run(playbook, registry)

    assert result.ok is True
    prompt = str(llm.await_args.args[1])
    assert "Todo 29" in prompt, "the model must see the whole result, not the first 120 chars"


async def test_the_narration_sees_every_item_even_when_the_record_keeps_fewer() -> None:
    """The record digest is bounded so history stops growing; the narration is not
    history. Seen live: an inbox fetch of five emails with bodies overran the
    4000-char record bound, the narration was handed the record's three, and
    the user's triage said "5 pulled, only 3 included" over a run in which every
    call had succeeded.
    """
    payload = json.dumps(
        {
            "fetched_count": 5,
            "messages": [{"id": f"msg_{i}", "body": "x" * 1200} for i in range(5)],
        }
    )
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, events_result=payload))
    playbook = _playbook(
        [PlaybookStep(id="mail", tool="list_events", args={"calendar_id": "primary"})]
    )

    result, llm = await _run(playbook, registry)

    assert result.ok is True
    prompt = str(llm.await_args.args[1])
    assert "msg_4" in prompt, "the narration must see every item the tool returned"
    assert len(result.trace[0].result_digest) <= RESULT_DIGEST_MAX_CHARS


# --- the one model call ----------------------------------------------------


class TestNarrationCall:
    """How the run's model calls are built, billed, and prompted.

    Everything about them is load-bearing: the schema each must return, the user
    its COGS lands on, the label it appears under in observability, and the
    material it is given to write from. A replay that silently narrates from an
    empty prompt still returns a plausible paragraph, which is exactly why the
    prompt's contents are pinned rather than the shape of the answer.
    """

    async def test_the_ask_call_is_a_structured_call_for_the_asks_only(self) -> None:
        """The mid-run call returns the ask schema, not the narration's: a call
        that could carry a result or a verdict mid-run is the bug this split
        removed."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        runnable = MagicMock()
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.")},
                ),
            ]
        )

        result, llm = await _run(
            playbook,
            registry,
            ask_fill=_ask_fill({"mail.body": "Twelve today."}),
            seams=_Seams(runnable=runnable),
        )

        assert result.ok is True, result.failure
        assert [call.args for call in runnable.call_args_list] == [
            (PlaybookAskFill,),
            (PlaybookNarration,),
        ]
        assert [call.kwargs["label"] for call in llm.await_args_list] == [
            "playbook_ask_fill",
            "playbook_narration",
        ]
        assert llm.await_args_list[0].kwargs["config"] == {"configurable": {"user_id": "u_1"}}
        # The mid-run call is metered too: built unmetered it is a replay's COGS
        # landing on nobody, which is exactly the line a background run hides.
        assert runnable.call_args_list[0].kwargs == {"config": {"configurable": {"user_id": "u_1"}}}
        assert _prompt_block(_ask_prompt(llm), "playbook") == playbook.description

    async def test_it_is_one_structured_call_metered_to_the_workflows_user(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        runnable = MagicMock()

        result, llm = await _run(_playbook(AGENDA_STEPS), registry, seams=_Seams(runnable=runnable))

        assert result.ok is True, result.failure
        assert runnable.call_args.args == (PlaybookNarration,)
        # Attribution, not budget: a replay's narration is COGS and has to land
        # on the workflow's owner at both halves of the call.
        assert runnable.call_args.kwargs["config"] == {"configurable": {"user_id": "u_1"}}
        assert llm.await_args.args[0] is runnable.return_value
        assert llm.await_args.kwargs["config"] == {"configurable": {"user_id": "u_1"}}
        assert llm.await_args.kwargs["label"] == "playbook_narration"

    async def test_the_prompt_carries_the_playbook_and_everything_that_ran(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(AGENDA_STEPS)

        result, llm = await _run(playbook, registry)

        prompt = str(llm.await_args.args[1])
        assert result.completed == [
            'events (list_events {"calendar_id":"primary"}) -> {"count": 12}',
            'mail (send_email {"to":"team@example.com"}) -> sent',
        ]
        assert playbook.description in prompt
        assert playbook.result_brief in prompt
        assert "\n".join(result.completed) in prompt
        # Narrated at the end, so nothing is outstanding: the prompt has no
        # still-to-run section at all, rather than an empty one the model could
        # read as "some steps are missing".
        assert "<still_to_run>" not in prompt

    async def test_the_end_call_is_given_the_result_brief_as_the_brief_to_write_to(self) -> None:
        """The brief is the only instruction on HOW to write the user's result.

        It is where classification, judgement and summarising live now that a
        playbook has no ask table to hide them in, so a narration prompt that
        drops it produces a competent summary of the wrong thing on every fire.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(AGENDA_STEPS)

        result, llm = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert f"written to this brief (result_brief): {playbook.result_brief}" in _result_prompt(
            llm
        )

    async def test_a_mid_run_ask_fill_is_told_what_has_not_happened_yet(self) -> None:
        """An ask written before the last step has to know what it is for.

        The ask fill fires as soon as a step needs a ``$ask``, which can be the
        first step. Without the steps still to come in the prompt, the model
        writes the field as if the run ended there.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Summarise the day.")},
                ),
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            ]
        )

        result, llm = await _run(
            playbook, registry, ask_fill=_ask_fill({"mail.body": "A quiet day."})
        )

        assert result.ok is True, result.failure
        prompt = _ask_prompt(llm)
        assert "mail (send_email)\nevents (list_events)" in prompt
        # Nothing has run yet at that point, and an empty section would read as
        # "the run did nothing" rather than "the run has not started".
        assert _prompt_block(prompt, "ran") == "nothing yet"

    async def test_the_prompt_states_every_slot_and_its_budget(self) -> None:
        """One call fills every slot, so the per-slot instruction and its budget
        can only travel in this prompt. The budget is the slot's own, not the
        default: a slot that asks for a line and is shown the 1024-token default
        gets a page, and the argument that carries it is the one that grows."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.", 256)},
                ),
            ]
        )

        result, llm = await _run(
            playbook, registry, ask_fill=_ask_fill({"mail.body": "Twelve today."})
        )

        assert result.ok is True, result.failure
        prompt = _ask_prompt(llm)
        assert "- mail.body: Write the digest." in prompt
        assert "budget: about 256 tokens" in prompt

    async def test_a_slot_the_model_ignored_is_named_on_the_wide_event(self) -> None:
        """A silently unwritten slot produces a run that reads as fine and is not.

        The step carrying it fails when its arguments are filled, far from the
        cause, so the only way to see that the model skipped a slot it was
        listed is this warning, which names the slot by its key.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.")},
                ),
            ]
        )

        with patch(f"{MODULE}.log") as log:
            result, _ = await _run(playbook, registry, ask_fill=_ask_fill())

        assert result.ok is False
        assert "mail.body was never written" in (result.failure or "")
        assert log.warning.call_count == 1
        assert "wrote nothing for some slots" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["missing_asks"] == ["mail.body"]
        assert log.warning.call_args.kwargs["playbook_id"] == playbook.playbook_id
        assert log.warning.call_args.kwargs["workflow_id"] == "wf_1"


# --- what the run is given to resolve against ------------------------------


class TestRunContext:
    """The material a replay resolves its placeholders against.

    Every one of these is silent when wrong: the step still runs, with a hole in
    its arguments, and the tool does something subtly different from what was
    recorded.
    """

    async def test_the_previous_runs_results_are_addressable_by_tool_name(self) -> None:
        """``$last_run`` is how a cursor survives between fires.

        It is looked up for this workflow and this user; a lookup that drifts off
        either one silently resolves the placeholder to nothing and the run
        starts over from the beginning of whatever it was paging through.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        previous = MagicMock()
        previous.trace = [RecordedCall(tool_name="list_events", result_digest='{"count": 7}')]

        async def find_latest(workflow_id: str, user_id: str) -> MagicMock | None:
            return previous if (workflow_id, user_id) == ("wf_1", "u_1") else None

        playbook = _playbook(
            [
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": "Last time $last_run.list_events.count"},
                )
            ]
        )

        result, _ = await _run(
            playbook, registry, seams=_Seams(find_previous=AsyncMock(side_effect=find_latest))
        )

        assert result.ok is True, result.failure
        assert recorder.calls[0][1]["body"] == "Last time 7"

    async def test_the_user_and_the_users_clock_reach_the_step(self) -> None:
        """``$now`` is the workflow's own zone, not the worker's.

        A worker in UTC resolving a Berlin workflow's ``$now`` sends a digest
        stamped an hour off, or on the wrong day either side of midnight.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [PlaybookStep(id="mail", tool="send_email", args={"to": "$user.email", "body": "$now"})]
        )

        result, _ = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert recorder.calls[0][1]["to"] == USER.email
        offset = datetime.now(Timezone.parse(USER.timezone).tzinfo).strftime("%z")
        assert recorder.calls[0][1]["body"].endswith(f"{offset[:3]}:{offset[3:]}")


# --- what the result reports -----------------------------------------------


async def test_a_finished_run_reports_every_step_it_completed() -> None:
    """``completed`` is what a fallback agent is told it must not do again.

    An empty list on a run that really did send the mail is how a workflow sends
    twice.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is True, result.failure
    assert result.completed == [
        'events (list_events {"calendar_id":"primary"}) -> {"count": 12}',
        'mail (send_email {"to":"team@example.com"}) -> sent',
    ]


async def test_a_run_that_stops_after_the_ask_fill_still_reports_the_call_it_made() -> None:
    """The ask fill is spent whether or not the run finished.

    ``llm_calls`` is the replay's cost line. A stopped run that already filled
    its asks and reports zero makes the replay look free exactly when it was
    not. The result call does not follow: a stopped run reports through
    ``failure``, not through a result.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="list_events"))
    playbook = _playbook(
        [
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": _slot("Summarise the day.")},
            ),
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
        ]
    )

    result, llm = await _run(playbook, registry, ask_fill=_ask_fill({"mail.body": "A quiet day."}))

    assert result.ok is False
    assert llm.await_count == 1
    assert result.llm_calls == 1
    assert result.completed == [
        'mail (send_email {"to":"team@example.com","body":"A quiet day."}) -> sent'
    ]


# --- how the replay graph is built -----------------------------------------


@contextmanager
def _spy_graph_build() -> Iterator[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Record how the step's graph was asked for, while still building the real one.

    The production functions still run, so every other assertion in the test is
    about a real graph; only the arguments are captured on the way through.
    """
    agent_calls: list[dict[str, Any]] = []
    stack_calls: list[dict[str, Any]] = []

    def spy_agent(llm: Any, tool_registry: Any, **kwargs: Any) -> Any:
        agent_calls.append({"llm": llm, "tool_registry": tool_registry, **kwargs})
        return real_create_agent(llm, tool_registry, **kwargs)

    def spy_stack(**kwargs: Any) -> Any:
        stack_calls.append(kwargs)
        return real_create_middleware_stack(**kwargs)

    with (
        patch(f"{MODULE}.create_agent", spy_agent),
        patch(f"{MODULE}.create_middleware_stack", spy_stack),
    ):
        yield agent_calls, stack_calls


class TestReplayGraphContract:
    """What a replayed step's graph is, and what it deliberately is not.

    A replay is only cheaper than an agent because the graph it runs has the
    thinking parts switched off. Each one back on is a silent regression: the
    accounting middleware bills a scripted turn as a model call, summarization
    compacts a history that does not exist, the subagent middleware puts a
    reasoning model back inside a run that has none, and retrieval lets a replay
    discover a tool the recorded run never used.
    """

    async def test_the_step_graph_is_scripted_with_the_recorded_call_and_nothing_else(
        self,
    ) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"})]
        )

        with _spy_graph_build() as (agent_calls, _):
            result, _llm = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert len(agent_calls) == 1
        kwargs = agent_calls[0]
        assert set(kwargs) == {"llm", "tool_registry", "tools_config", "agent_config"}
        assert kwargs["agent_config"].agent_name == "playbook_replay"
        # A replay never discovers tools: it runs calls a real run already made.
        assert kwargs["tools_config"].disable_retrieve_tools is True
        assert isinstance(kwargs["llm"], ScriptedModel)
        assert [(c.name, c.args) for c in kwargs["llm"].script] == [
            ("list_events", {"calendar_id": "primary"})
        ]
        assert sorted(kwargs["tools_config"].initial_tool_ids) == [
            "file_notes",
            "list_events",
            "send_email",
        ]

    async def test_the_step_graph_has_the_thinking_middleware_switched_off(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"})]
        )

        with _spy_graph_build() as (agent_calls, stack_calls):
            result, _llm = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert stack_calls == [
            {
                "agent_name": "playbook_replay",
                "chat_llm": None,
                "accounting": AccountingOptions(enabled=False),
                "context": ContextOptions(summarize=False),
                "subagent": SubagentStackOptions(enabled=False),
            }
        ]
        # The stack the graph was actually given is the one built above, not a
        # default stack quietly assembled somewhere else.
        assert agent_calls[0]["agent_config"].middleware is not None


# --- the narration prompt's sections ---------------------------------------


def _prompt_block(prompt: str, tag: str) -> str:
    """The text inside one ``<tag>`` section of a model call's prompt."""
    return prompt.split(f"<{tag}>\n", 1)[1].split(f"\n</{tag}>", 1)[0]


class TestNarrationSections:
    """The exact material the model calls write from.

    The model cannot tell a section that is wrong from one that is right, so a
    prompt assembled from the wrong steps produces a confident, wrong result.
    Every section is pinned as a whole rather than sampled, because a section
    that silently loses a line reads as complete.
    """

    async def test_the_still_to_run_section_starts_at_the_step_being_run(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.")},
                ),
                PlaybookStep(
                    handoff="calendar_agent",
                    steps=[
                        PlaybookStep(id="more", tool="list_events", args={"calendar_id": "second"})
                    ],
                ),
            ]
        )

        result, llm = await _run(
            playbook,
            registry,
            ask_fill=_ask_fill({"mail.body": "Twelve today."}),
            seams=_Seams(subagent=_FakeSubagent()),
        )

        assert result.ok is True, result.failure
        # The ask fill fires at step 2, so steps 2 onward are still to come and
        # step 1 is not: it already ran and is listed as such.
        assert _prompt_block(_ask_prompt(llm), "still_to_run") == (
            "mail (send_email)\nhandoff to calendar_agent\nmore (list_events)"
        )

    async def test_a_playbook_with_no_slots_says_so_rather_than_leaving_it_blank(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, llm = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is True, result.failure
        assert _prompt_block(str(llm.await_args.args[1]), "asks") == "none"

    async def test_a_slot_is_listed_with_its_budget_and_nothing_it_cannot_have(self) -> None:
        """A slot is two lines and no more.

        It has no set of steps to read: it is written from everything listed as
        already run, because an inline slot has no way to name a subset of it.
        The block is pinned whole, so a third line reappearing — a works-from
        naming steps the slot cannot address — fails here rather than silently
        narrowing what the model writes from.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(id="mail", tool="send_email", args={"to": "$trigger.to"}),
                PlaybookStep(
                    id="note",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.")},
                ),
            ]
        )

        result, llm = await _run(
            playbook, registry, ask_fill=_ask_fill({"note.body": "Twelve today."})
        )

        assert result.ok is True, result.failure
        assert _prompt_block(_ask_prompt(llm), "asks") == "\n".join(
            [
                "- note.body: Write the digest.",
                f"  budget: about {DEFAULT_ASK_MAX_TOKENS} tokens",
            ]
        )
        # One step per line: run together, two calls read as one call whose
        # result is the other's, and the slot is written from that.
        assert _prompt_block(_ask_prompt(llm), "ran") == (
            'events (list_events {"calendar_id":"primary"}) -> {"count": 12}\n'
            'mail (send_email {"to":"team@example.com"}) -> sent'
        )

    async def test_a_slot_inside_a_list_argument_still_triggers_the_ask_fill(self) -> None:
        """Slots are found wherever they are, not only at the top level.

        A step whose slot sits inside a list would otherwise run before the
        model ever wrote it, and send the slot's own dict as the argument. The
        key names the position: the list index is part of the address.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(
                    id="notes",
                    tool="file_notes",
                    args={"items": ["intro", _slot("Write the digest.")]},
                )
            ]
        )

        result, llm = await _run(
            playbook, registry, ask_fill=_ask_fill({"notes.items.1": "Twelve today."})
        )

        assert result.ok is True, result.failure
        assert llm.await_count == 2
        assert recorder.calls[0][1]["items"] == ["intro", "Twelve today."]
        assert "- notes.items.1: Write the digest." in _ask_prompt(llm)


# --- when each model call happens ------------------------------------------


class TestCallOrder:
    """When the two model calls fire, relative to the steps.

    Seen live on "write a note (an $ask slot), then create_todo with it": one call
    filled the slot AND wrote the result AND judged the run, before create_todo
    ran. The verdict said "the create_todo step had not run, so no todo was
    created", the replay was distrusted and the agent redid the fire. The ask
    has to be written before the step that needs it; the result and the verdict
    have to be written after the last step, from its result.
    """

    ASK_STEPS: ClassVar[list[PlaybookStep]] = [
        PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
        PlaybookStep(
            id="mail",
            tool="send_email",
            args={"to": "$trigger.to", "body": {"$ask": "Write the digest."}},
        ),
    ]

    async def test_the_ask_call_precedes_its_step_and_the_result_call_follows_the_last(
        self,
    ) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        answers = [_ask_fill({"mail.body": "Twelve today."}), _narration()]
        tools_run_before_each_call: list[list[str]] = []

        async def model(runnable: object, prompt: object, **kwargs: object) -> object:
            tools_run_before_each_call.append([name for name, _ in recorder.calls])
            return answers[len(tools_run_before_each_call) - 1]

        result, llm = await _run(
            _playbook(self.ASK_STEPS),
            registry,
            seams=_Seams(llm=AsyncMock(side_effect=model)),
        )

        assert result.ok is True, result.failure
        assert tools_run_before_each_call == [
            ["list_events"],
            ["list_events", "send_email"],
        ]
        # The end call writes from the last step's actual result, which only
        # exists because it ran after that step.
        assert 'mail (send_email {"to":"team@example.com","body":' in _result_prompt(llm)
        assert result.llm_calls == 2

    async def test_the_result_call_lists_nothing_as_still_to_run_when_the_run_completed(
        self,
    ) -> None:
        """A completed run has nothing outstanding, and a section that says
        otherwise is what the verdict judged against."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, llm = await _run(
            _playbook(self.ASK_STEPS), registry, ask_fill=_ask_fill({"mail.body": "x"})
        )

        assert result.ok is True, result.failure
        prompt = _result_prompt(llm)
        assert "<still_to_run>" not in prompt
        assert _prompt_block(prompt, "ran") == "\n".join(result.completed)
        # The ask call, by contrast, was told what was still to come.
        assert _prompt_block(_ask_prompt(llm), "still_to_run") == "mail (send_email)"

    async def test_the_ask_calls_answers_resolve_the_later_steps_arguments(self) -> None:
        """A slot's text is read from the ask call, not from the result call,
        which writes no slots at all."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, _ = await _run(
            _playbook(self.ASK_STEPS),
            registry,
            ask_fill=_ask_fill({"mail.body": "Written by the ask call."}),
            narration=_narration("Written by the result call."),
        )

        assert result.ok is True, result.failure
        assert recorder.calls[1][1]["body"] == "Written by the ask call."
        assert result.text == "Written by the result call."

    async def test_the_result_call_sees_the_filled_asks_for_context(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, llm = await _run(
            _playbook(self.ASK_STEPS),
            registry,
            ask_fill=_ask_fill({"mail.body": "Twelve today."}),
        )

        assert result.ok is True, result.failure
        assert _prompt_block(_result_prompt(llm), "asks") == "- mail.body: Twelve today."


# --- what a stopped run reports --------------------------------------------


class TestFailureReport:
    """The report a stopped run hands back to the worker.

    It is the only thing the worker and the fallback agent get: which step
    stopped it, on what tool, why, and what had already really happened. A
    report that loses the position or the reason turns a precise handover into
    "something went wrong somewhere".
    """

    async def test_a_denied_tool_names_its_position_and_the_reason(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
        playbook = _playbook(
            [
                PlaybookStep(
                    handoff="calendar_agent",
                    steps=[
                        PlaybookStep(id="mail", tool="send_email", args={"to": "x@example.com"})
                    ],
                )
            ]
        )

        result, _ = await _run(playbook, registry, seams=_Seams(subagent=_FakeSubagent()))

        assert result.ok is False
        assert result.failure == (
            "Playbook stopped at step 2 (send_email): no tool named 'send_email' is available "
            "in this run's tool space. Completed: nothing. Nothing after that step ran."
        )

    async def test_a_tool_outside_a_handoffs_bound_set_is_refused_by_position(self) -> None:
        """A handoff that cannot retrieve may only run the tools it bound at startup.

        Its space also holds the always-available tools, so "in the space" is not
        the same question as "this delegation could have called it". A replay
        that conflates them runs a call the recorded delegation never could.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
        playbook = _playbook(
            [
                PlaybookStep(
                    handoff="calendar_agent",
                    steps=[PlaybookStep(id="mine", tool="grep", args={"pattern": "x"})],
                )
            ]
        )

        result, _ = await _run(playbook, registry, seams=_Seams(subagent=_FakeSubagent()))

        assert result.ok is False
        assert result.failure == (
            "Playbook stopped at step 2 (grep): grep is outside the bound tool set of this "
            "handoff, which cannot retrieve. Completed: nothing. Nothing after that step ran."
        )

    async def test_a_stale_placeholder_names_its_position(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(id="mail", tool="send_email", args={"to": "$steps.gone.address"}),
            ]
        )

        result, _ = await _run(playbook, registry)

        assert result.ok is False
        assert result.failure.startswith("Playbook stopped at step 2 (send_email): ")
        assert "$steps.gone.address" in result.failure

    async def test_a_gated_call_names_its_position_and_tool(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, _ = await _run(_playbook(AGENDA_STEPS), registry, policy="ask")

        assert result.ok is False
        assert result.failure.startswith(
            "Playbook stopped at step 1 (list_events): refused by the approval gate: "
        )

    async def test_an_unknown_handoff_target_names_its_position(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, seams=_Seams(subagent=None))

        assert result.ok is False
        assert result.failure == (
            "Playbook stopped at step 1 (handoff): no subagent named 'calendar_agent' exists. "
            "Completed: nothing. Nothing after that step ran."
        )

    async def test_the_report_quotes_every_step_that_had_already_run(self) -> None:
        """A fallback agent is told what not to redo, so a dropped line is a double send."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(id="mail", tool="send_email", args={"to": "$trigger.to"}),
                PlaybookStep(id="gone", tool="send_email", args={"to": "$steps.gone.address"}),
            ]
        )

        result, _ = await _run(playbook, registry)

        assert result.ok is False
        assert (
            'Completed: events (list_events {"calendar_id":"primary"}) -> {"count": 12}; mail (send_email {"to":"team@example.com"}) -> sent.'
            in result.failure
        )


# --- the trace ---------------------------------------------------------------


class TestTrace:
    """What lands on the durable record, and under what identity.

    The trace is what stops the fallback agent from repeating a side effect and
    what a later run's ``$last_run`` reads. A call recorded under the wrong
    category, without its arguments, or with the handoff's identity missing is a
    record that cannot be replayed or audited afterwards.
    """

    async def test_a_recorded_call_carries_its_category_and_arguments(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is True, result.failure
        assert [(c.tool_name, c.tool_category) for c in result.trace] == [
            ("list_events", "calendar"),
            ("send_email", "mail"),
        ]
        assert result.trace[0].args == {"calendar_id": "primary"}
        assert result.trace[1].args == {"to": "team@example.com"}
        # Marked as the replay's own: the next run's empty-result check compares
        # only against replayed calls, so a call recorded as an agent's is a
        # comparison that silently never happens.
        assert [call.replayed for call in result.trace] == [True, True]

    async def test_a_handoff_is_recorded_as_the_delegation_it_was(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})

        result, _ = await _run(
            _playbook(HANDOFF_PLAYBOOK), registry, seams=_Seams(subagent=_FakeSubagent())
        )

        assert result.ok is True, result.failure
        assert result.trace[0].tool_name == "handoff"
        assert result.trace[0].tool_category == "handoff"
        assert result.trace[0].args == {"subagent_id": "calendar_agent"}

    async def test_a_failing_call_is_recorded_with_its_error_and_its_subagent(self) -> None:
        """A side effect that failed inside a handoff still has to be on the record.

        Attributed to the subagent that ran it, because a trace flattened to the
        executor level cannot tell a later run which space the call came from.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(recorder, failing="list_events"), spaces={"calendar": ["list_events"]}
        )

        result, _ = await _run(
            _playbook(HANDOFF_PLAYBOOK), registry, seams=_Seams(subagent=_FakeSubagent())
        )

        assert result.ok is False
        assert result.trace[1].tool_name == "list_events"
        assert result.trace[1].subagent_id == "calendar_agent"
        assert "calendar unavailable" in result.trace[1].result_digest

    async def test_a_result_that_cannot_be_recorded_stops_the_run_with_the_steps_before_it(
        self,
    ) -> None:
        """The record was built outside the step's guard, so a digest the model
        refused raised out of ``run_playbook`` and the steps already on the
        trace were lost with it. The run always comes back as a result."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(AGENDA_STEPS)

        def over_long(output: object, max_chars: int = RESULT_DIGEST_MAX_CHARS) -> str:
            if output == "sent":
                return "x" * (RESULT_DIGEST_MAX_CHARS + 1)
            return build_result_digest(output, max_chars=max_chars)

        with patch(f"{MODULE}.build_result_digest", over_long), patch(f"{MODULE}.log") as log:
            result, _ = await _run(playbook, registry)

        assert result.ok is False
        assert result.failure is not None
        assert "step 2 (send_email)" in result.failure
        assert "could not be recorded" in result.failure
        assert [call.tool_name for call in result.trace] == ["list_events"]
        assert [name for name, _ in recorder.calls] == ["list_events", "send_email"]
        # A call that ran and could not be written down is the one failure that
        # leaves a real side effect off the record, so the event carries every
        # id needed to find it by hand afterwards.
        assert log.exception.call_args.args == (
            f"{LogTag.WORKFLOW} Playbook step ran but its result could not be recorded",
        )
        assert log.exception.call_args.kwargs == {
            "playbook_id": playbook.playbook_id,
            "workflow_id": "wf_1",
            "tool_name": "send_email",
            "error_type": "ValidationError",
        }


# --- the identity a replayed call runs under -------------------------------


class TestCallIdentity:
    async def test_a_top_level_step_runs_untagged_and_a_handoff_child_runs_as_the_subagent(
        self,
    ) -> None:
        """Tools branch on the subagent they are running for, so the tag is behaviour.

        A handoff child running untagged reaches the integration as the executor,
        which is not the boundary the recorded delegation had.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    handoff="calendar_agent",
                    steps=[
                        PlaybookStep(id="more", tool="list_events", args={"calendar_id": "second"})
                    ],
                ),
            ]
        )

        result, _ = await _run(playbook, registry, seams=_Seams(subagent=_FakeSubagent()))

        assert result.ok is True, result.failure
        assert recorder.calls[0][1]["subagent"] is None
        assert recorder.calls[1][1]["subagent"] == "calendar_agent"


# --- results that are not a plain string -----------------------------------


def _special_tools(recorder: _Recorder) -> dict[str, BaseTool]:
    """Tools whose results take the shapes a replay has to survive."""

    @tool
    async def big_report(query: Annotated[str, "Query"]) -> ToolMessage:
        """Produce a report too large to return inline, and offload it to a file.

        Carries the same structured marker the compaction middleware stamps on a
        message it offloads, which is the one shape ``read_offload`` reads.
        """
        recorder.calls.append(("big_report", {"query": query}))
        return ToolMessage(
            content="first rows",
            tool_call_id=scripted_call_id(0),
            name="big_report",
            additional_kwargs=mark_offload(
                {},
                {
                    "path": "/workspace/report.jsonl",
                    "bytes": 4096,
                    "fmt": "jsonl",
                    "producer": "big_report",
                    "records": 120,
                },
            ),
        )

    @tool
    async def stash(note: Annotated[str, "Note"]) -> Command:
        """Write to the graph's state instead of answering."""
        recorder.calls.append(("stash", {"note": note}))
        return Command(update={"todos": []})

    @tool
    async def rich_result(topic: Annotated[str, "Topic"]) -> ToolMessage:
        """Answer in content blocks rather than one string."""
        recorder.calls.append(("rich_result", {"topic": topic}))
        return ToolMessage(
            content=[{"type": "text", "text": "twelve events"}],
            tool_call_id=scripted_call_id(0),
            name="rich_result",
        )

    @tool
    async def send_note(body: Annotated[str, "Body"]) -> str:
        """Send a note."""
        recorder.calls.append(("send_note", {"body": body}))
        return "sent"

    @tool
    async def keep(since: Annotated[Any, "Anything the playbook recorded"]) -> str:
        """Take an argument of whatever shape the record holds."""
        recorder.calls.append(("keep", {"since": since}))
        return "kept"

    @tool
    async def needs_approval(topic: Annotated[str, "Topic"]) -> ToolMessage:
        """Answer the way the gate does when it refuses: a verdict, in blocks."""
        recorder.calls.append(("needs_approval", {"topic": topic}))
        return ToolMessage(
            content=[{"type": "text", "text": "not approved for a background run"}],
            tool_call_id=scripted_call_id(0),
            name="needs_approval",
            additional_kwargs={HIL_STATUS_KWARG: "denied"},
        )

    return {
        "big_report": big_report,
        "stash": stash,
        "rich_result": rich_result,
        "send_note": send_note,
        "keep": keep,
        "needs_approval": needs_approval,
    }


class TestNonStringResults:
    """A recorded call does not always come back as a string, and a replay has to cope.

    Each of these shapes is produced by a real tool in the registry, and each one
    mishandled looks like a successful step that quietly carried nothing: an
    offloaded file the next step cannot open, a state update reported as a
    result, or content blocks flattened to nothing.
    """

    async def test_an_offloaded_result_is_addressable_as_a_file_by_the_next_step(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_special_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="report", tool="big_report", args={"query": "everything"}),
                PlaybookStep(id="note", tool="send_note", args={"body": "$steps.report.file"}),
            ]
        )

        result, _ = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert recorder.calls[1][1]["body"] == "/workspace/report.jsonl"

    async def test_a_call_that_produced_no_result_stops_the_run_and_says_so(self) -> None:
        """A tool that only updates state answers nothing, and the run must not guess.

        Treating "no result" as an empty success records a call that returned
        nothing as if it had returned something, and every later ``$steps``
        reference resolves against a hole.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_special_tools(recorder))
        playbook = _playbook([PlaybookStep(id="s", tool="stash", args={"note": "later"})])

        result, _ = await _run(playbook, registry)

        assert result.ok is False
        assert result.failure == (
            "Playbook stopped at step 1 (stash): the graph produced no result for this call. "
            "Completed: nothing. Nothing after that step ran."
        )

    async def test_a_content_block_result_is_recorded_as_its_text_not_as_nothing(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_special_tools(recorder))
        playbook = _playbook([PlaybookStep(id="r", tool="rich_result", args={"topic": "today"})])

        result, _ = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert "twelve events" in result.completed[0]
        assert "twelve events" in result.trace[0].result_digest


async def test_a_handoff_child_can_carry_a_slot() -> None:
    """The ask fill a child triggers is the parent playbook's, not the handoff's.

    A handoff's children are run against the same playbook, so a child that
    carries a slot fills it from the whole playbook. Filling it from anything
    else has nothing to write from. The key is the CHILD's id, not the
    handoff's: a key built from the handoff would name a step with no arguments.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
    playbook = _playbook(
        [
            PlaybookStep(
                handoff="calendar_agent",
                steps=[
                    PlaybookStep(
                        id="more",
                        tool="list_events",
                        args={"calendar_id": _slot("Which calendar?")},
                    )
                ],
            )
        ]
    )

    result, llm = await _run(
        playbook,
        registry,
        ask_fill=_ask_fill({"more.calendar_id": "primary"}),
        seams=_Seams(subagent=_FakeSubagent()),
    )

    assert result.ok is True, result.failure
    assert recorder.calls[0][1]["calendar_id"] == "primary"
    assert _prompt_block(_ask_prompt(llm), "still_to_run") == "more (list_events)"


def test_a_scripted_turn_is_a_bare_tool_call_and_nothing_else() -> None:
    """The exact shape of the turn the agent loop is handed.

    ``content`` must be empty: a scripted turn is a call, not an answer, and any
    text on it is prose the run never produced that still reaches the message
    history and the user-facing stream. The call's ``type`` is what LangChain
    routes on, so a tool call carrying anything else is dropped on the floor and
    the step silently never runs.
    """
    model = ScriptedModel(
        script=[ScriptedCall(name="list_events", args={"calendar_id": "primary"})]
    )

    message = model.turn_for([HumanMessage(content="go")])

    assert message.content == ""
    assert len(message.tool_calls) == 1
    call = message.tool_calls[0]
    assert call["name"] == "list_events"
    assert call["args"] == {"calendar_id": "primary"}
    assert call["id"] == scripted_call_id(0)
    assert call["type"] == "tool_call"


# --- results that are wrong without being errors ----------------------------


def _previous_run(*calls: RecordedCall) -> AsyncMock:
    """The previous execution's trace, as ``find_latest_with_trace`` hands it back."""
    previous = MagicMock()
    previous.trace = list(calls)
    return AsyncMock(return_value=previous)


class TestErrorEnvelope:
    """A tool that catches its own failure answers with a success-status message
    whose body says it failed. That is a failed step: recorded, then stopped."""

    async def test_a_success_false_envelope_stops_the_step_with_its_message(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(
                recorder,
                events_result='{"success": false, "error": "Insufficient permission: calendar"}',
            )
        )

        result, llm = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is False
        assert result.suspect is None
        assert result.failure is not None
        assert result.failure.startswith(
            "Playbook stopped at step 1 (list_events): Insufficient permission: calendar."
        )
        assert [name for name, _ in recorder.calls] == ["list_events"]
        assert llm.await_count == 0

    async def test_the_failed_call_is_still_on_the_record(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(recorder, events_result='{"success": false, "error": "expired token"}')
        )

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert [call.tool_name for call in result.trace] == ["list_events"]
        assert result.trace[0].result_digest == '{"success": false, "error": "expired token"}'

    async def test_a_non_empty_error_field_fails_even_without_a_success_flag(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(recorder, events_result='{"error": "rate limited", "items": []}')
        )

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is False
        assert "rate limited" in (result.failure or "")

    async def test_a_bare_success_false_still_names_a_reason(self) -> None:
        """An envelope that says only ``success: false`` has no words of its own.

        The report is the whole handover, so the runner supplies the one fact it
        does have rather than passing an empty reason to the agent.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"success": false}'))

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is False
        assert result.failure is not None
        assert result.failure.startswith(
            "Playbook stopped at step 1 (list_events): the tool reported success=false."
        )

    async def test_a_success_envelope_with_a_null_error_is_a_result(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(recorder, events_result='{"success": true, "error": null, "items": [1]}')
        )

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is True, result.failure
        assert [name for name, _ in recorder.calls] == ["list_events", "send_email"]

    async def test_the_quoted_message_is_bounded(self) -> None:
        long_error = "x" * 400
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(recorder, events_result=json.dumps({"success": False, "message": long_error}))
        )

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is False
        assert "x" * 120 in (result.failure or "")
        assert "x" * 121 not in (result.failure or "")


class TestSuspectVerdict:
    """A run that completes can still be wrong. ``suspect`` says why, without
    stopping anything: every step runs, the result is written, and the worker
    decides what a distrusted result is worth."""

    PREVIOUS_HAD_THREE = RecordedCall(
        replayed=True,
        tool_name="list_events",
        result_digest='{"items": [{"id": 1}, {"id": 2}, {"id": 3}]}',
    )

    async def test_empty_where_the_previous_replay_had_items_stops_the_run_there(self) -> None:
        """The record's verdict is known the moment the step returns, so the steps
        after it (the send) do not run on data nobody trusts. No narration
        either: there is nothing to deliver, the agent finishes this fire."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))

        result, llm = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            seams=_Seams(find_previous=_previous_run(self.PREVIOUS_HAD_THREE)),
        )

        assert result.ok is True, result.failure
        assert result.suspect == "list_events returned no items where the previous run returned 3"
        assert result.suspect_source == "record"
        assert [name for name, _ in recorder.calls] == ["list_events"]
        assert result.text == ""
        assert llm.await_count == 0

    async def test_a_run_stopped_on_the_records_word_still_reports_what_it_did(self) -> None:
        """That early return is a full result, not a stub.

        The agent finishes this fire from it: without the trace it repeats the
        send whose side effect already happened, without ``completed`` it does
        not know which steps those were, and without ``llm_calls`` the ask fill
        the run already paid for reads as free.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        playbook = _playbook(
            [
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.")},
                ),
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            ]
        )

        result, llm = await _run(
            playbook,
            registry,
            ask_fill=_ask_fill({"mail.body": "Twelve today."}),
            seams=_Seams(find_previous=_previous_run(self.PREVIOUS_HAD_THREE)),
        )

        assert result.ok is True, result.failure
        assert result.suspect_source == "record"
        assert [call.tool_name for call in result.trace] == ["send_email", "list_events"]
        assert result.completed == [
            'mail (send_email {"to":"team@example.com","body":"Twelve today."}) -> sent',
            'events (list_events {"calendar_id":"primary"}) -> {"items": []}',
        ]
        assert result.llm_calls == 1
        assert llm.await_count == 1

    async def test_a_suspect_narration_with_no_reason_still_says_why(self) -> None:
        """The verdict is acted on by the worker, so "suspect, no reason" would
        distrust a run and tell nobody what to look at."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        narration = PlaybookNarration(result="Twelve events.", outcome="suspect", reason="")

        result, _ = await _run(_playbook(AGENDA_STEPS), registry, narration=narration)

        assert result.suspect == "the narration judged the results suspect"
        assert result.suspect_source == "narration"

    async def test_a_previous_agent_runs_call_is_not_what_the_replay_is_compared_with(self) -> None:
        """An authoring or heal run probes the same tool broadly; its full result
        says nothing about what the frozen call should return."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        previous = _previous_run(
            RecordedCall(tool_name="list_events", result_digest='{"items": [1, 2, 3]}')
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS), registry, seams=_Seams(find_previous=previous)
        )

        assert result.suspect is None
        assert [name for name, _ in recorder.calls] == ["list_events", "send_email"]

    async def test_an_empty_list_inside_a_result_envelope_counts_as_empty(self) -> None:
        """GAIA tools answer in envelopes: the list is at ``data.messages``, not
        at the top. Seen live: a Gmail fetch of nothing is
        ``{"data": {"fetched_count": 0, "messages": []}}``."""
        recorder = _Recorder()
        registry = _FakeRegistry(
            _tools(recorder, events_result='{"data": {"fetched_count": 0, "messages": []}}')
        )
        previous = _previous_run(
            RecordedCall(
                replayed=True,
                tool_name="list_events",
                result_digest='{"data": {"fetched_count": 2, "messages": [{"id": 1}, {"id": 2}]}}',
            )
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS), registry, seams=_Seams(find_previous=previous)
        )

        assert result.ok is True, result.failure
        assert result.suspect == "list_events returned no items where the previous run returned 2"

    async def test_empty_with_no_previous_run_is_not_suspect(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))

        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is True, result.failure
        assert result.suspect is None

    async def test_empty_where_the_previous_run_was_also_empty_is_not_suspect(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        previous = _previous_run(
            RecordedCall(replayed=True, tool_name="list_events", result_digest='{"items": []}')
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS), registry, seams=_Seams(find_previous=previous)
        )

        assert result.suspect is None

    async def test_the_previous_run_is_read_by_tool_name_not_position(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        previous = _previous_run(
            RecordedCall(replayed=True, tool_name="send_email", result_digest='{"items": [1, 2]}'),
            self.PREVIOUS_HAD_THREE,
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS), registry, seams=_Seams(find_previous=previous)
        )

        assert result.suspect == "list_events returned no items where the previous run returned 3"

    async def test_the_previous_runs_last_call_of_the_tool_is_the_one_compared(self) -> None:
        """``$last_run`` resolves a tool called twice to its LAST result (the
        attempt that worked); the empty-result check read the FIRST, so a retry
        that had items after an empty first attempt was never compared."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        previous = _previous_run(
            RecordedCall(replayed=True, tool_name="list_events", result_digest='{"items": []}'),
            self.PREVIOUS_HAD_THREE,
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS), registry, seams=_Seams(find_previous=previous)
        )

        assert result.suspect == "list_events returned no items where the previous run returned 3"

    async def test_the_narrations_verdict_becomes_the_reason(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        narration = PlaybookNarration(
            result="No events were found.", outcome="suspect", reason="the agenda came back empty"
        )

        result, _ = await _run(_playbook(AGENDA_STEPS), registry, narration=narration)

        assert result.ok is True, result.failure
        assert result.suspect == "the agenda came back empty"
        # The text is handed over untouched: flagging it is the worker's job.
        assert result.text == "No events were found."

    async def test_a_narration_that_says_ok_leaves_the_run_trusted(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, _ = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            narration=PlaybookNarration(result="Twelve events.", outcome="ok", reason=""),
        )

        assert result.suspect is None

    async def test_the_deterministic_reason_wins_over_the_narrations(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        narration = PlaybookNarration(
            result="Nothing today.", outcome="suspect", reason="the model's own take"
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            narration=narration,
            seams=_Seams(find_previous=_previous_run(self.PREVIOUS_HAD_THREE)),
        )

        assert result.suspect == "list_events returned no items where the previous run returned 3"

    async def test_a_record_verdict_names_the_record_as_its_source(self) -> None:
        """The worker treats a deterministic verdict and the model's own opinion
        differently, so the result has to say which one spoke."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))

        result, _ = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            seams=_Seams(find_previous=_previous_run(self.PREVIOUS_HAD_THREE)),
        )

        assert result.suspect is not None
        assert result.suspect_source == "record"

    async def test_a_narration_verdict_names_the_narration_as_its_source(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        narration = PlaybookNarration(
            result="No events were found.", outcome="suspect", reason="the agenda came back empty"
        )

        result, _ = await _run(_playbook(AGENDA_STEPS), registry, narration=narration)

        assert result.suspect == "the agenda came back empty"
        assert result.suspect_source == "narration"

    async def test_when_both_speak_the_source_is_the_record(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, events_result='{"items": []}'))
        narration = PlaybookNarration(
            result="Nothing today.", outcome="suspect", reason="the model's own take"
        )

        result, _ = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            narration=narration,
            seams=_Seams(find_previous=_previous_run(self.PREVIOUS_HAD_THREE)),
        )

        assert result.suspect_source == "record"

    async def test_a_trusted_run_has_no_suspect_source(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, _ = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            narration=PlaybookNarration(result="Twelve events.", outcome="ok", reason=""),
        )

        assert result.suspect is None
        assert result.suspect_source is None

    async def test_a_stopped_run_never_carries_a_suspect_reason(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder, failing="list_events"))

        result, _ = await _run(
            _playbook(AGENDA_STEPS),
            registry,
            seams=_Seams(find_previous=_previous_run(self.PREVIOUS_HAD_THREE)),
        )

        assert result.ok is False
        assert result.suspect is None

    async def test_the_narration_is_asked_for_a_verdict(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        _, llm = await _run(_playbook(AGENDA_STEPS), registry)

        prompt = _result_prompt(llm)
        assert "Answer suspect when a result is empty where the task expects items" in prompt
        # Seen live: the verdict ran mid-run and judged a step that had not
        # happened yet as "not done". The end call must be told to judge only
        # what is listed, and that the list is the whole run.
        assert "Judge only the steps listed under ran" in prompt
        assert "—" not in prompt

    async def test_a_suspect_verdict_from_the_end_call_names_the_narration_as_its_source(
        self,
    ) -> None:
        """With asks, the verdict comes from the SECOND call. It still propagates
        as the narration's, and the ask call has no say in it."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    id="mail",
                    tool="send_email",
                    args={"to": "$trigger.to", "body": _slot("Write the digest.")},
                ),
            ]
        )
        narration = PlaybookNarration(
            result="Twelve events, but the mail did not go out.",
            outcome="suspect",
            reason="send_email answered with nothing that looks like a delivery",
        )

        result, llm = await _run(
            playbook,
            registry,
            ask_fill=_ask_fill({"mail.body": "Twelve today."}),
            narration=narration,
        )

        assert result.ok is True, result.failure
        assert llm.await_count == 2
        assert result.suspect == "send_email answered with nothing that looks like a delivery"
        assert result.suspect_source == "narration"
        assert result.text == "Twelve events, but the mail did not go out."


class TestTheNarrationSeesTheArguments:
    async def test_each_ran_line_carries_the_arguments_the_call_ran_with(self) -> None:
        """Seen live: told only the tool name and twenty results, the verdict
        called a month of read mail "unread, last 24 hours". The arguments are
        what it has to judge against."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, llm = await _run(_playbook(AGENDA_STEPS), registry)

        prompt = str(llm.await_args.args[1])
        assert '(list_events {"calendar_id":"primary"})' in prompt
        assert '(send_email {"to":"team@example.com"})' in prompt
        assert result.completed[0].startswith('events (list_events {"calendar_id":"primary"}) -> ')


class TestANarrationMustSaySomething:
    def test_a_result_with_no_letter_or_digit_is_refused(self) -> None:
        with pytest.raises(ValidationError) as raised:
            PlaybookNarration(result="...", outcome="ok")

        # The refusal's own words: this is what the failure report hands the
        # agent, and "raised ValidationError: None" names nothing to act on.
        assert raised.value.errors()[0]["msg"] == "Value error, the result says nothing"

    def test_a_short_real_answer_is_fine(self) -> None:
        assert PlaybookNarration(result="No new todos.", outcome="ok").result == "No new todos."


async def test_a_replay_that_finished_without_a_narration_refuses_to_report_a_result() -> None:
    """``ok=True`` with no narration would be a run delivering an empty result.

    Every path to here has written one, so reaching it means the narration was
    lost between the call and the result; the run says so instead of handing the
    user a blank success.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    with (
        patch(f"{MODULE}._narrate", AsyncMock(return_value=None)),
        pytest.raises(RuntimeError) as raised,
    ):
        await _run(_playbook(AGENDA_STEPS), registry)

    assert str(raised.value) == "playbook replay finished every step without a narration"


#: Two slotted steps around a fetch: the mail's body is written from the events,
#: and the note's body is written from what the mail actually went out as.
TWO_SLOTTED_STEPS = [
    PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
    PlaybookStep(
        id="mail",
        tool="send_email",
        args={"to": "$trigger.to", "body": _slot("Write the digest.")},
    ),
    PlaybookStep(
        id="note",
        tool="send_email",
        args={"to": "$user.email", "body": _slot("Note what the mail said.")},
    ),
]


async def test_each_slotted_step_gets_its_own_ask_call_listing_only_its_slots() -> None:
    """Two steps carrying slots, two ask calls, and neither is shown the other's.

    The keys are what say which step a call is answering for, so a call listed
    both steps' keys is a call being asked to write an argument for a step that
    is still several results away.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    fills = AsyncMock(
        side_effect=[
            _ask_fill({"mail.body": "Twelve today."}),
            _ask_fill({"note.body": "Told the team about twelve."}),
            _narration(),
        ]
    )

    result, llm = await _run(_playbook(TWO_SLOTTED_STEPS), registry, seams=_Seams(llm=fills))

    assert result.ok is True, result.failure
    assert llm.await_count == 3
    assert result.llm_calls == 3
    assert _prompt_block(_ask_prompt(llm, 0), "asks").splitlines()[::2] == [
        "- mail.body: Write the digest."
    ]
    assert _prompt_block(_ask_prompt(llm, 1), "asks").splitlines()[::2] == [
        "- note.body: Note what the mail said."
    ]
    assert recorder.calls[1][1]["body"] == "Twelve today."
    assert recorder.calls[2][1]["body"] == "Told the team about twelve."


async def test_a_later_steps_slot_is_written_from_the_steps_that_already_ran() -> None:
    """The bug this split fixes: a slot answered before the run reached it.

    One call at the first slotted step wrote every slot in the playbook, so the
    note's "what the mail said" was answered with nothing listed under ran — the
    mail had not gone out yet — and that text reached a real tool. Its call now
    fires at its own step, with the fetch and the mail both listed as run.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    fills = AsyncMock(
        side_effect=[
            _ask_fill({"mail.body": "Twelve today."}),
            _ask_fill({"note.body": "Told the team about twelve."}),
            _narration(),
        ]
    )

    result, llm = await _run(_playbook(TWO_SLOTTED_STEPS), registry, seams=_Seams(llm=fills))

    assert result.ok is True, result.failure
    assert _prompt_block(_ask_prompt(llm, 0), "ran") == (
        'events (list_events {"calendar_id":"primary"}) -> {"count": 12}'
    )
    assert _prompt_block(_ask_prompt(llm, 1), "ran") == (
        'events (list_events {"calendar_id":"primary"}) -> {"count": 12}\n'
        'mail (send_email {"to":"team@example.com","body":"Twelve today."}) -> sent'
    )


async def test_a_fill_that_omits_a_later_steps_key_stops_the_run_at_that_step() -> None:
    """Each call is checked against its own step's slots, not the playbook's.

    A step whose call came back without its key must not run: the argument would
    still hold the slot's own dict. Checked at the later step because that is
    where the earlier fill's answers no longer stand in for it — the run has
    already spent a call, so "some slot was written" says nothing about this one.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    fills = AsyncMock(
        side_effect=[_ask_fill({"mail.body": "Twelve today."}), _ask_fill({"note.elsewhere": "x"})]
    )

    with patch(f"{MODULE}.log") as log:
        result, llm = await _run(_playbook(TWO_SLOTTED_STEPS), registry, seams=_Seams(llm=fills))

    assert result.ok is False
    assert result.failure is not None
    assert result.failure.startswith(
        "Playbook stopped at step 3 (send_email): note.body was never written."
    )
    # The step never ran, and the mail before it did: the fill that answered
    # that step's own slot is not undone by the one that failed.
    assert [name for name, _ in recorder.calls] == ["list_events", "send_email"]
    assert llm.await_count == 2
    assert log.warning.call_args.kwargs["missing_asks"] == ["note.body"]


# --- one fill per slotted step ----------------------------------------------


async def test_a_handoff_childs_slot_is_filled_by_its_own_call_like_any_other() -> None:
    """A child inside a handoff is a step, so it gets a step's ask call.

    Its slot is not swept up by the call the first top-level slot triggered:
    the child runs last, and a fill made before the two steps ahead of it would
    write its argument from a run that had not reached it. The keys stay the
    child's own, so the answers still land where the evaluator looks for them.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
    playbook = _playbook(
        [
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": _slot("Write the digest.")},
            ),
            PlaybookStep(
                id="note",
                tool="send_email",
                args={"to": "$user.email", "body": _slot("Write the note.")},
            ),
            PlaybookStep(
                handoff="calendar_agent",
                steps=[
                    PlaybookStep(
                        id="more",
                        tool="list_events",
                        args={"calendar_id": _slot("Which calendar?")},
                    )
                ],
            ),
        ]
    )

    fills = AsyncMock(
        side_effect=[
            _ask_fill({"mail.body": "Twelve events today."}),
            _ask_fill({"note.body": "Filed for the record."}),
            _ask_fill({"more.calendar_id": "second"}),
            _narration(),
        ]
    )

    result, llm = await _run(
        playbook,
        registry,
        seams=_Seams(subagent=_FakeSubagent(), llm=fills),
    )

    assert result.ok is True, result.failure
    assert llm.await_count == 4
    assert result.llm_calls == 4
    assert recorder.calls[0][1]["body"] == "Twelve events today."
    assert recorder.calls[1][1]["body"] == "Filed for the record."
    assert recorder.calls[2][1]["calendar_id"] == "second"
    # One call per slotted step, in execution order, each keyed by
    # ``<step id>.<argument path>`` — the key the answers are looked back up by.
    assert [
        _prompt_block(_ask_prompt(llm, index), "asks").splitlines()[0] for index in range(3)
    ] == [
        "- mail.body: Write the digest.",
        "- note.body: Write the note.",
        "- more.calendar_id: Which calendar?",
    ]


async def test_each_fill_fires_at_its_own_step_and_no_earlier() -> None:
    """A run whose first and third steps carry slots makes one fill at each.

    The first fires before anything has run, which is all its step can be
    written from. The second fires after the two steps in front of it, which is
    the whole point: written at the first one it would answer from a run that
    had not fetched anything yet.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": _slot("Write the digest.")},
            ),
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="note",
                tool="send_email",
                args={"to": "$user.email", "body": _slot("Write the note.")},
            ),
        ]
    )
    answers = [
        _ask_fill({"mail.body": "Twelve today."}),
        _ask_fill({"note.body": "Filed."}),
        _narration(),
    ]
    tools_run_before_each_call: list[list[str]] = []

    async def model(runnable: object, prompt: object, **kwargs: object) -> object:
        tools_run_before_each_call.append([name for name, _ in recorder.calls])
        return answers[len(tools_run_before_each_call) - 1]

    result, llm = await _run(playbook, registry, seams=_Seams(llm=AsyncMock(side_effect=model)))

    assert result.ok is True, result.failure
    assert tools_run_before_each_call == [
        [],
        ["send_email", "list_events"],
        ["send_email", "list_events", "send_email"],
    ]
    assert llm.await_count == 3
    assert result.llm_calls == 3
    assert recorder.calls[2][1]["body"] == "Filed."


async def test_a_slot_is_filled_before_the_placeholder_beside_it_is_resolved() -> None:
    """Filling runs first, so a slot and a ``$steps`` reference in one argument
    both arrive resolved.

    The order is load-bearing in both directions: resolution first would meet the
    slot's own dict and stop the run, and a fill that did not leave an ordinary
    string behind would send the placeholder next to it as literal text.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="notes",
                tool="file_notes",
                args={
                    "items": [_slot("Write the digest."), "Found $steps.events.count events"],
                },
            ),
        ]
    )

    result, _ = await _run(
        playbook, registry, ask_fill=_ask_fill({"notes.items.0": "Twelve today."})
    )

    assert result.ok is True, result.failure
    assert recorder.calls[1][1]["items"] == ["Twelve today.", "Found 12 events"]


async def test_a_fill_that_omits_a_slot_stops_the_run_at_that_step_naming_the_key() -> None:
    """A slot with no text is a hole in a real tool call, so the step must not run.

    The report names the key the model was listed, which is the only thing that
    says which of the slots came back empty, and it lists the steps that DID run
    so the agent finishing the fire does not repeat their side effects.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$trigger.to", "body": _slot("Write the digest.")},
            ),
        ]
    )

    result, _ = await _run(
        playbook, registry, ask_fill=_ask_fill({"mail.elsewhere": "Twelve today."})
    )

    assert result.ok is False
    assert result.failure is not None
    assert result.failure.startswith(
        "Playbook stopped at step 2 (send_email): mail.body was never written."
    )
    # The step never ran; the one before it did, and the report says so.
    assert [name for name, _ in recorder.calls] == ["list_events"]
    assert result.completed == ['events (list_events {"calendar_id":"primary"}) -> {"count": 12}']


async def test_a_refusal_carrying_content_blocks_is_quoted_rather_than_lost() -> None:
    """The gate's verdict IS the step's result, and it is not always a string.

    A refusal flattened to nothing comes back as "refused by the approval gate:"
    with no reason after it, which is the one thing the report exists to carry.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_special_tools(recorder))
    playbook = _playbook([PlaybookStep(id="ask", tool="needs_approval", args={"topic": "today"})])

    result, _ = await _run(playbook, registry)

    assert result.ok is False
    assert result.failure is not None
    assert "not approved for a background run" in result.failure
    # Nothing ran, so nothing may reach the record the next run reads.
    assert result.trace == []


# --- how the step's graph is invoked ----------------------------------------


@contextmanager
def _spy_graph_invocations() -> Iterator[list[dict[str, Any]]]:
    """Record the state and config each step's compiled graph was invoked with.

    The real graph is still built and still run, so everything else the test
    asserts is about a real replay; only the call is captured on the way past.
    """
    invocations: list[dict[str, Any]] = []

    class _SpyGraph:
        def __init__(self, graph: Any) -> None:
            self._graph = graph

        async def ainvoke(self, state: Any, config: Any = None, **kwargs: Any) -> Any:
            invocations.append({"state": dict(state), "config": dict(config or {})})
            return await self._graph.ainvoke(state, config=config, **kwargs)

    class _SpyBuilder:
        def __init__(self, builder: Any) -> None:
            self._builder = builder

        def compile(self, *args: Any, **kwargs: Any) -> _SpyGraph:
            return _SpyGraph(self._builder.compile(*args, **kwargs))

    def spy_agent(*args: Any, **kwargs: Any) -> _SpyBuilder:
        return _SpyBuilder(real_create_agent(*args, **kwargs))

    with patch(f"{MODULE}.create_agent", spy_agent):
        yield invocations


class TestTheStepGraphInvocation:
    """The state and config a replayed step's graph is actually run with.

    Every one of these is silent when wrong. A state whose keys the runtime does
    not recognise starts the step with defaults instead of the empty history a
    replay means; a recursion limit written under a key LangGraph does not read
    is no bound at all, so a tool whose result loops the graph runs away; and the
    identity fields are what the tool resolves its user and its scope from.
    """

    async def test_the_graph_starts_from_an_empty_state_under_the_runs_identity(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"})]
        )

        with _spy_graph_invocations() as invocations:
            result, _llm = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert len(invocations) == 1
        assert invocations[0]["state"] == {"messages": [], "todos": []}
        config = invocations[0]["config"]
        assert set(config) == {"configurable", "metadata", "recursion_limit"}
        # One tool call plus the turn that ends the loop, with room to spare.
        assert config["recursion_limit"] == 8
        # ``get_user_id_from_config`` reads metadata and nothing else.
        assert config["metadata"] == {"user_id": "u_1"}
        assert config["configurable"]["user_id"] == "u_1"
        assert config["configurable"]["conversation_id"] == "conv_1"
        assert config["configurable"]["execution_mode"] == "background"
        assert config["configurable"]["stream_id"].startswith("playbook_")
        # A top-level step is not tagged as anyone's subagent.
        assert "subagent_id" not in config["configurable"]


# --- the arguments the narration is shown -----------------------------------


class TestTheArgumentsTheNarrationSees:
    """The rendered arguments on each ``completed`` line.

    They are the model's only view of what a call actually ran with, and the
    line is built AFTER the call, so a renderer that raises loses a run whose
    side effects already happened.
    """

    async def test_an_argument_that_is_not_json_is_rendered_rather_than_raising(self) -> None:
        """A stored playbook comes back from Mongo with real dates in its args."""
        recorder = _Recorder()
        registry = _FakeRegistry(_special_tools(recorder))
        moment = datetime(2026, 8, 27, 9, 30, tzinfo=UTC)
        playbook = _playbook([PlaybookStep(id="k", tool="keep", args={"since": moment})])

        result, _ = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert result.completed == [f'k (keep {{"since":"{moment}"}}) -> kept']

    async def test_arguments_that_fit_the_bound_are_shown_whole(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        args: dict[str, Any] = {"to": "team@example.com", "body": "y" * 365}
        rendered = json.dumps(args, separators=(",", ":"), default=str)
        assert len(rendered) == 400, "the bound itself: this test is the boundary"
        playbook = _playbook([PlaybookStep(id="mail", tool="send_email", args=args)])

        result, _ = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert result.completed == [f"mail (send_email {rendered}) -> sent"]

    async def test_arguments_past_the_bound_are_cut_and_say_so(self) -> None:
        """One character over, and the line is cut with the mark that says it was.

        Unmarked, the model reads a truncated argument as the whole argument and
        judges the call against a filter it never ran with.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        args: dict[str, Any] = {"to": "team@example.com", "body": "y" * 366}
        rendered = json.dumps(args, separators=(",", ":"), default=str)
        assert len(rendered) == 401
        playbook = _playbook([PlaybookStep(id="mail", tool="send_email", args=args)])

        result, _ = await _run(playbook, registry)

        assert result.ok is True, result.failure
        assert result.completed == [f"mail (send_email {rendered[:400]}...) -> sent"]


async def test_the_narration_reads_the_result_uncut_where_the_record_trims_it() -> None:
    """The record trims long strings and marks them; the narration must not see that.

    Seen live at the record's bound: the model was handed bodies cut to 200
    characters with a marker on the end and reported the run as truncated. The
    two bounds are separate for exactly this reason.
    """
    payload = json.dumps({"messages": [{"id": f"msg_{i}", "body": "x" * 1200} for i in range(5)]})
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, events_result=payload))
    playbook = _playbook([PlaybookStep(id="mail", tool="list_events", args={"calendar_id": "in"})])

    result, _ = await _run(playbook, registry)

    assert result.ok is True, result.failure
    assert "msg_4" in result.completed[0]
    assert "x" * 1200 in result.completed[0]
    assert RECORD_CUT_MARKER not in result.completed[0]
    # The record keeps its own, tighter bound; inside a JSON digest the cut
    # marker rides json.dumps and its ellipsis arrives \u2026-escaped.
    assert "\\u2026[cut]" in result.trace[0].result_digest


async def test_the_ask_fill_adds_to_the_runs_llm_count_rather_than_resetting_it() -> None:
    """The counter is a running total across the replay's model calls; the fill
    must add its one call, not restart the tally."""
    run = _bare_run()
    run.llm_calls = 5
    playbook = _playbook([PlaybookStep(id="mail", tool="list_events", args={})])
    fill = PlaybookAskFill(asks=[])

    with (
        patch(f"{MODULE}.background_structured_runnable", MagicMock()),
        patch(f"{MODULE}.ainvoke_llm", AsyncMock(return_value=fill)),
    ):
        await _fill_asks(playbook, playbook.steps[0], run, pending=[])

    assert run.llm_calls == 6
    assert run.ask_fill is fill


# --- guards on states the models rule out ------------------------------------


def _bare_run(registry: Any = None) -> _Run:
    """A ``_Run`` at the first position, for calling one internal directly."""
    return _Run(
        registry=registry or _FakeRegistry({}),
        base=RunContext(
            user=USER,
            now=datetime.now(UTC),
            trigger={},
            steps={},
            last_run={},
            asks={},
        ),
        configurable={
            "stream_id": "playbook_test",
            "user_id": "u_1",
            "conversation_id": "conv_1",
            "execution_mode": "background",
        },
        position=1,
    )


class TestGuardsOnStatesTheModelsRuleOut:
    """Branches a valid document cannot currently reach, asserted directly.

    ``PlaybookStep`` enforces exactly one of ``tool``/``handoff``, a playbook
    carries at least one step, and a run the record already distrusted returns
    before the narration is ever written. Each guard below is what happens when
    one of those stops holding — a document written by an older schema, a
    handoff whose children were dropped — and a guard nobody exercises is a
    guard that has quietly stopped guarding.
    """

    async def test_a_handoff_with_no_target_names_the_empty_id(self) -> None:
        step = PlaybookStep.model_construct(id="h", tool=None, args={}, handoff=None, steps=[])

        with patch(f"{TOOL_SPACE_MODULE}.get_subagent_by_id", lambda subagent_id: None):
            failure = await _run_handoff(_playbook(AGENDA_STEPS), step, _bare_run())

        assert failure is not None
        assert failure.label == "handoff"
        assert failure.reason == "no subagent named '' exists"

    async def test_a_step_with_no_tool_names_the_empty_name(self) -> None:
        step = PlaybookStep.model_construct(id="s", tool=None, args={}, handoff=None, steps=[])
        space = ToolSpace(tools={}, runtime=None, subagent_id=None)

        failure = await _run_tool_step(_playbook(AGENDA_STEPS), step, _bare_run(), space)

        assert failure is not None
        assert failure.position == 1
        assert failure.reason == "no tool named '' exists"

    def test_a_playbook_with_no_slots_renders_them_as_a_word(self) -> None:
        assert _render_asks([]) == "none"

    def test_a_record_verdict_is_reported_as_the_records(self) -> None:
        run = _bare_run()
        run.suspect = "list_events returned no items where the previous run returned 3"

        assert _suspect_verdict(run, _narration()) == (run.suspect, "record")

    async def test_a_narration_written_from_nothing_says_nothing_ran(self) -> None:
        """An empty section reads as a run whose steps are missing from the list,
        which is the verdict this prompt spends a paragraph forbidding."""
        run = _bare_run()

        with (
            patch(f"{MODULE}.background_structured_runnable", MagicMock()),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(return_value=_narration())) as llm,
        ):
            await _narrate(_playbook(AGENDA_STEPS), run)

        assert _prompt_block(str(llm.await_args.args[1]), "ran") == "nothing"
