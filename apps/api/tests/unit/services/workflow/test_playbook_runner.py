"""Replaying a playbook: what actually runs, what is refused, and what it costs.

The runner's whole value is that it is cheaper than the agent and still safe, so
the tests defend both halves. Safety is not asserted against a stubbed gate: the
steps go through the REAL graph, the real middleware chain and the real HIL gate,
which is the only way to tell that a replay still gates every call now that the
runner no longer calls the gate itself.

One replay makes exactly one model call no matter how many ``$ask`` fields it has
to fill; the scripted model's turns are not model calls and never reach a provider.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from typing import Annotated, Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer
from langgraph.types import Command

from app.agents.middleware.factory import create_middleware_stack as real_create_middleware_stack
from app.agents.workspace.offload import mark_offload
from app.models.playbook_models import PlaybookAsk, PlaybookDocument, PlaybookStep
from app.models.workflow_execution_models import RESULT_DIGEST_MAX_CHARS, RecordedCall
from app.override.langgraph_bigtool.create_agent import create_agent as real_create_agent
from app.services.hil.prompts import UNPAUSABLE_DENIAL_TEMPLATE
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import (
    PlaybookAskAnswer,
    PlaybookNarration,
    PlaybookRunResult,
    run_playbook,
)
from app.services.workflow.playbook.scripted_model import (
    REPLAY_FINISHED_CONTENT,
    ScriptedCall,
    ScriptedModel,
    scripted_call_id,
)
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


def _playbook(
    steps: list[PlaybookStep], ask: dict[str, PlaybookAsk] | None = None
) -> PlaybookDocument:
    return PlaybookDocument(
        description="Mail the day's agenda",
        steps=steps,
        ask=ask or {},
        synthesize="Say how many events there were and that the mail went out.",
        workflow_id="wf_1",
        user_id="u_1",
        workflow_hash="hash_1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _narration(result: str = "Twelve events, mail sent.", **asks: str) -> PlaybookNarration:
    return PlaybookNarration(
        asks=[PlaybookAskAnswer(name=name, text=text) for name, text in asks.items()],
        result=result,
    )


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


async def _run(
    playbook: PlaybookDocument,
    registry: _FakeRegistry,
    narration: PlaybookNarration | None = None,
    policy: str = "allow",
    subagent: _FakeSubagent | None = None,
    runnable: MagicMock | None = None,
    find_previous: AsyncMock | None = None,
    llm: AsyncMock | None = None,
) -> tuple[PlaybookRunResult, AsyncMock]:
    """Run the playbook with mocked seams; hands back the result and the LLM mock.

    ``runnable``, ``find_previous`` and ``llm`` let a test hold on to the seam
    it is asserting about: how the one model call is built, what the previous
    execution's trace was looked up with, and what the model call does.
    """
    llm = llm or AsyncMock(return_value=narration or _narration())
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
        # The narration runs on whatever provider the deployment uses, so the
        # runnable is built then invoked. Both halves are stubbed: the test cares
        # that ONE model call happens and what it returns, not which lane served it.
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


async def test_one_llm_call_covers_two_asks_and_the_synthesis() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail",
                tool="send_email",
                args={"to": "$ask.recipient", "body": "$ask.body"},
            ),
        ],
        ask={
            "recipient": PlaybookAsk(prompt="Who should get this?", uses=["events"]),
            "body": PlaybookAsk(prompt="Write the digest.", uses=["events"]),
        },
    )
    narration = _narration(recipient="team@example.com", body="Twelve events today.")

    result, llm = await _run(playbook, registry, narration=narration)

    assert llm.await_count == 1
    assert result.ok is True, result.failure
    assert recorder.calls[1][1] == {"to": "team@example.com", "body": "Twelve events today."}
    assert result.text == "Twelve events, mail sent."
    assert result.llm_calls == 1


async def test_a_playbook_with_no_asks_still_makes_exactly_one_call() -> None:
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
    assert result.completed == ['events (list_events) -> {"count": 12}']


async def test_the_failure_names_what_already_completed() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="send_email"))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert "events (list_events)" in (result.failure or "")


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

    result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, subagent=_FakeSubagent())

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

    result, _ = await _run(playbook, registry, subagent=_FakeSubagent())

    assert result.ok is False
    assert recorder.calls == []
    assert "send_email" in (result.failure or "")
    assert [call.tool_name for call in result.trace] == ["handoff"]


async def test_an_unknown_handoff_target_stops_the_run() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, subagent=None)

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

    async def mcp_client(user_id: str) -> MagicMock:
        client = MagicMock()
        client.ensure_connected = AsyncMock(return_value=[tools["send_email"]])
        return client

    with patch(f"{TOOL_SPACE_MODULE}.get_mcp_client", mcp_client):
        result, _ = await _run(playbook, registry, subagent=_FakeMcpSubagent())

    assert result.ok is True, result.failure
    assert [name for name, _ in recorder.calls] == ["send_email"]
    assert [call.tool_name for call in result.trace] == ["handoff", "send_email"]


# --- a step or the narration that raises ------------------------------------


async def test_a_step_that_raises_stops_the_run_with_the_completed_steps_on_record() -> None:
    """An exception out of the step's graph used to escape ``run_playbook``
    before any result existed, so the worker never saw ``ok=False`` and the
    trace of the steps that had already run — with their side effects — was
    lost with it."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    def exploding_agent(**kwargs: Any) -> Any:
        if kwargs["llm"].script[0].name == "send_email":
            raise RuntimeError("graph exploded")
        return real_create_agent(**kwargs)

    with patch(f"{MODULE}.create_agent", exploding_agent):
        result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is False
    assert [call.tool_name for call in result.trace] == ["list_events"]
    assert result.completed == ['events (list_events) -> {"count": 12}']
    assert result.failure is not None
    assert result.failure.startswith("Playbook stopped at step 2 (send_email): ")
    assert "RuntimeError" in result.failure
    assert "graph exploded" in result.failure
    assert "events (list_events)" in result.failure


async def test_a_step_that_raises_is_logged_with_its_error_type() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    def exploding_agent(**kwargs: Any) -> Any:
        raise RuntimeError("graph exploded")

    with patch(f"{MODULE}.create_agent", exploding_agent), patch(f"{MODULE}.log") as log:
        await _run(_playbook(AGENDA_STEPS), registry)

    assert log.exception.call_count == 1
    assert log.exception.call_args.kwargs["error_type"] == "RuntimeError"
    assert log.exception.call_args.kwargs["tool_name"] == "list_events"


async def test_a_narration_that_raises_stops_the_run_with_every_step_on_record() -> None:
    """The narration is the last thing a finished replay does; a raise there
    dropped a trace in which EVERY step had already run."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(
        _playbook(AGENDA_STEPS), registry, llm=AsyncMock(side_effect=TimeoutError("model"))
    )

    assert result.ok is False
    assert [call.tool_name for call in result.trace] == ["list_events", "send_email"]
    assert len(result.completed) == 2
    assert result.failure is not None
    assert "narration" in result.failure
    assert "TimeoutError" in result.failure
    assert result.llm_calls == 0


async def test_a_mid_run_narration_that_raises_stops_before_the_step_that_needed_it() -> None:
    """A step addressing ``$ask`` triggers the narration first. If that raises,
    the step must not run with the ask unfilled."""
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    playbook = _playbook(
        [
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            PlaybookStep(
                id="mail", tool="send_email", args={"to": "$trigger.to", "body": "$ask.body"}
            ),
        ],
        ask={"body": PlaybookAsk(prompt="Write the body", uses=["events"])},
    )

    result, _ = await _run(playbook, registry, llm=AsyncMock(side_effect=TimeoutError("model")))

    assert result.ok is False
    assert [name for name, _ in recorder.calls] == ["list_events"]
    assert [call.tool_name for call in result.trace] == ["list_events"]
    assert result.failure is not None
    assert result.failure.startswith("Playbook stopped at step 2 (narration): ")


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
    """How the run's single model call is built, billed, and prompted.

    It is the only call in a replay, so everything about it is load-bearing: the
    schema it must return, the user its COGS lands on, the label it appears under
    in observability, and the material it is given to write from. A replay that
    silently narrates from an empty prompt still returns a plausible paragraph,
    which is exactly why the prompt's contents are pinned rather than the shape
    of the answer.
    """

    async def test_it_is_one_structured_call_metered_to_the_workflows_user(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        runnable = MagicMock()

        result, llm = await _run(_playbook(AGENDA_STEPS), registry, runnable=runnable)

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
            'events (list_events) -> {"count": 12}',
            "mail (send_email) -> sent",
        ]
        assert playbook.description in prompt
        assert playbook.synthesize in prompt
        assert "\n".join(result.completed) in prompt
        # Narrated at the end, so nothing is outstanding and the model must be
        # told so rather than left to read an empty section as "unknown".
        assert "nothing, every step has run" in prompt

    async def test_a_mid_run_narration_is_told_what_has_not_happened_yet(self) -> None:
        """A result written before the last step still has to describe the whole run.

        The narration fires as soon as a step needs a ``$ask``, which can be the
        first step. Without the steps still to come in the prompt, the model
        writes the run up as if it ended there.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [
                PlaybookStep(
                    id="mail", tool="send_email", args={"to": "$trigger.to", "body": "$ask.summary"}
                ),
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
            ],
            ask={"summary": PlaybookAsk(prompt="Summarise the day.", uses=[])},
        )

        result, llm = await _run(playbook, registry, narration=_narration(summary="A quiet day."))

        assert result.ok is True, result.failure
        prompt = str(llm.await_args.args[1])
        assert "mail (send_email)\nevents (list_events)" in prompt
        # Nothing has run yet at that point, and an empty section would read as
        # "the run did nothing" rather than "the run has not started".
        assert "nothing yet" in prompt

    async def test_the_prompt_states_every_declared_ask_and_its_budget(self) -> None:
        """One call fills every ask, so the per-ask instruction can only travel in the prompt."""
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        ask = PlaybookAsk(prompt="Write the digest.", uses=["events"])
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(
                    id="mail", tool="send_email", args={"to": "$trigger.to", "body": "$ask.body"}
                ),
            ],
            ask={"body": ask},
        )

        result, llm = await _run(playbook, registry, narration=_narration(body="Twelve today."))

        assert result.ok is True, result.failure
        prompt = str(llm.await_args.args[1])
        assert f"- body: {ask.prompt}" in prompt
        assert f"budget: about {ask.max_tokens} tokens" in prompt

    async def test_an_ask_the_model_ignored_is_named_on_the_wide_event(self) -> None:
        """A silently unwritten ask produces a run that reads as fine and is not.

        The step addressing it fails with a placeholder error far from the cause,
        so the only way to see that the model skipped a field it was asked for is
        this warning.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            AGENDA_STEPS,
            ask={"body": PlaybookAsk(prompt="Write the digest.", uses=["events"])},
        )

        with patch(f"{MODULE}.log") as log:
            result, _ = await _run(playbook, registry, narration=_narration())

        assert result.ok is True, result.failure
        assert log.warning.call_count == 1
        assert "wrote nothing for declared asks" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["missing_asks"] == ["body"]
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

        result, _ = await _run(playbook, registry, find_previous=AsyncMock(side_effect=find_latest))

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
        'events (list_events) -> {"count": 12}',
        "mail (send_email) -> sent",
    ]


async def test_a_run_that_stops_after_narrating_still_reports_the_call_it_made() -> None:
    """The narration is spent whether or not the run finished.

    ``llm_calls`` is the replay's cost line. A stopped run that already narrated
    and reports zero makes the replay look free exactly when it was not.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder, failing="list_events"))
    playbook = _playbook(
        [
            PlaybookStep(
                id="mail", tool="send_email", args={"to": "$trigger.to", "body": "$ask.summary"}
            ),
            PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
        ],
        ask={"summary": PlaybookAsk(prompt="Summarise the day.", uses=[])},
    )

    result, llm = await _run(playbook, registry, narration=_narration(summary="A quiet day."))

    assert result.ok is False
    assert llm.await_count == 1
    assert result.llm_calls == 1
    assert result.completed == ["mail (send_email) -> sent"]


# --- how the replay graph is built -----------------------------------------


@contextmanager
def _spy_graph_build() -> Iterator[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Record how the step's graph was asked for, while still building the real one.

    The production functions still run, so every other assertion in the test is
    about a real graph; only the arguments are captured on the way through.
    """
    agent_calls: list[dict[str, Any]] = []
    stack_calls: list[dict[str, Any]] = []

    def spy_agent(**kwargs: Any) -> Any:
        agent_calls.append(kwargs)
        return real_create_agent(**kwargs)

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
        assert set(kwargs) == {
            "llm",
            "tool_registry",
            "agent_name",
            "disable_retrieve_tools",
            "initial_tool_ids",
            "middleware",
        }
        assert kwargs["agent_name"] == "playbook_replay"
        # A replay never discovers tools: it runs calls a real run already made.
        assert kwargs["disable_retrieve_tools"] is True
        assert isinstance(kwargs["llm"], ScriptedModel)
        assert [(c.name, c.args) for c in kwargs["llm"].script] == [
            ("list_events", {"calendar_id": "primary"})
        ]
        assert sorted(kwargs["initial_tool_ids"]) == ["file_notes", "list_events", "send_email"]

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
                "enable_accounting": False,
                "enable_summarization": False,
                "enable_subagent": False,
            }
        ]
        # The stack the graph was actually given is the one built above, not a
        # default stack quietly assembled somewhere else.
        assert agent_calls[0]["middleware"] is not None


# --- the narration prompt's sections ---------------------------------------


def _prompt_block(prompt: str, tag: str) -> str:
    """The text inside one ``<tag>`` section of the narration prompt."""
    return prompt.split(f"<{tag}>\n", 1)[1].split(f"\n</{tag}>", 1)[0]


class TestNarrationSections:
    """The exact material the one model call writes from.

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
                    id="mail", tool="send_email", args={"to": "$trigger.to", "body": "$ask.body"}
                ),
                PlaybookStep(
                    handoff="calendar_agent",
                    steps=[
                        PlaybookStep(id="more", tool="list_events", args={"calendar_id": "second"})
                    ],
                ),
            ],
            ask={"body": PlaybookAsk(prompt="Write the digest.", uses=[])},
        )

        result, llm = await _run(
            playbook,
            registry,
            narration=_narration(body="Twelve today."),
            subagent=_FakeSubagent(),
        )

        assert result.ok is True, result.failure
        # The narration fires at step 2, so steps 2 onward are still to come and
        # step 1 is not: it already ran and is listed as such.
        assert _prompt_block(str(llm.await_args.args[1]), "still_to_run") == (
            "mail (send_email)\nhandoff to calendar_agent\nmore (list_events)"
        )

    async def test_a_playbook_with_no_asks_says_so_rather_than_leaving_it_blank(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))

        result, llm = await _run(_playbook(AGENDA_STEPS), registry)

        assert result.ok is True, result.failure
        assert _prompt_block(str(llm.await_args.args[1]), "asks") == "none"

    async def test_each_ask_arrives_with_its_budget_and_the_steps_it_works_from(self) -> None:
        """An ask names the steps it is written from, and they must reach the model.

        Without them the model writes the field from the whole run, which is the
        difference between "the digest of the calendar" and "a summary of
        everything that happened".
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        ask = PlaybookAsk(prompt="Write the digest.", uses=["events", "mail"])
        playbook = _playbook(
            [
                PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
                PlaybookStep(id="mail", tool="send_email", args={"to": "$trigger.to"}),
                PlaybookStep(
                    id="note", tool="send_email", args={"to": "$trigger.to", "body": "$ask.body"}
                ),
            ],
            ask={"body": ask},
        )

        result, llm = await _run(playbook, registry, narration=_narration(body="Twelve today."))

        assert result.ok is True, result.failure
        assert _prompt_block(str(llm.await_args.args[1]), "asks") == "\n".join(
            [
                f"- body: {ask.prompt}",
                f"  budget: about {ask.max_tokens} tokens",
                '  works from: events (list_events) -> {"count": 12}; mail (send_email) -> sent',
            ]
        )

    async def test_an_ask_inside_a_list_argument_still_triggers_the_narration(self) -> None:
        """Placeholders are found wherever they are, not only at the top level.

        A step whose ``$ask`` sits inside a list would otherwise run before the
        model ever wrote the field, and fail on a placeholder that was going to
        be filled one line later.
        """
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder))
        playbook = _playbook(
            [PlaybookStep(id="notes", tool="file_notes", args={"items": ["intro", "$ask.body"]})],
            ask={"body": PlaybookAsk(prompt="Write the digest.", uses=[])},
        )

        result, llm = await _run(playbook, registry, narration=_narration(body="Twelve today."))

        assert result.ok is True, result.failure
        assert llm.await_count == 1
        assert recorder.calls[0][1]["items"] == ["intro", "Twelve today."]


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

        result, _ = await _run(playbook, registry, subagent=_FakeSubagent())

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

        result, _ = await _run(playbook, registry, subagent=_FakeSubagent())

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

        result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, subagent=None)

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
            'Completed: events (list_events) -> {"count": 12}; mail (send_email) -> sent.'
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

    async def test_a_handoff_is_recorded_as_the_delegation_it_was(self) -> None:
        recorder = _Recorder()
        registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})

        result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, subagent=_FakeSubagent())

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

        result, _ = await _run(_playbook(HANDOFF_PLAYBOOK), registry, subagent=_FakeSubagent())

        assert result.ok is False
        assert result.trace[1].tool_name == "list_events"
        assert result.trace[1].subagent_id == "calendar_agent"
        assert "calendar unavailable" in result.trace[1].result_digest


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

        result, _ = await _run(playbook, registry, subagent=_FakeSubagent())

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

    return {
        "big_report": big_report,
        "stash": stash,
        "rich_result": rich_result,
        "send_note": send_note,
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


async def test_a_handoff_child_can_address_an_ask() -> None:
    """The narration a child triggers is the parent playbook's, not the handoff's.

    A handoff's children are run against the same playbook, so a child that
    needs a ``$ask`` narrates from the whole playbook. Narrating from anything
    else has nothing to write the field from.
    """
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder), spaces={"calendar": ["list_events"]})
    playbook = _playbook(
        [
            PlaybookStep(
                handoff="calendar_agent",
                steps=[
                    PlaybookStep(id="more", tool="list_events", args={"calendar_id": "$ask.which"})
                ],
            )
        ],
        ask={"which": PlaybookAsk(prompt="Which calendar?", uses=[])},
    )

    result, llm = await _run(
        playbook, registry, narration=_narration(which="primary"), subagent=_FakeSubagent()
    )

    assert result.ok is True, result.failure
    assert recorder.calls[0][1]["calendar_id"] == "primary"
    assert _prompt_block(str(llm.await_args.args[1]), "still_to_run") == "more (list_events)"


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
