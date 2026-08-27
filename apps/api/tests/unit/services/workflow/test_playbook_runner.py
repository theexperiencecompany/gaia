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
from typing import Annotated, Any, ClassVar
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer

from app.models.playbook_models import PlaybookAsk, PlaybookDocument, PlaybookStep
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

MODULE = "app.services.workflow.playbook.runner"
GATE = "app.services.hil.gate"

USER = PlaybookUser(email="ada@example.com", name="Ada", timezone="Europe/Berlin")


class _Recorder:
    """Collects the calls the tools actually received, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []


def _tools(recorder: _Recorder, *, failing: str | None = None) -> dict[str, BaseTool]:
    @tool
    async def list_events(calendar_id: Annotated[str, "Calendar"], config: RunnableConfig) -> str:
        """List calendar events."""
        # Both reads are the point: a tool inside a graph resolves its user
        # through metadata and streams through the pregel runtime, and a replay
        # that supplies neither comes back with an error string that looks like
        # a result. Calling them here makes that a failure, not a silent empty.
        get_stream_writer()({"progress": "listing"})
        recorder.calls.append(
            ("list_events", {"calendar_id": calendar_id, "user": get_user_id_from_config(config)})
        )
        if failing == "list_events":
            raise ValueError("calendar unavailable")
        return '{"count": 12}'

    @tool
    async def send_email(to: Annotated[str, "Recipient"], body: Annotated[str, "Body"] = "") -> str:
        """Send an email."""
        recorder.calls.append(("send_email", {"to": to, "body": body}))
        if failing == "send_email":
            raise ValueError("rejected argument 'body'")
        return "sent"

    return {"list_events": list_events, "send_email": send_email}


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
) -> tuple[PlaybookRunResult, AsyncMock]:
    """Run the playbook with mocked seams; hands back the result and the LLM mock."""
    llm = AsyncMock(return_value=narration or _narration())
    with (
        patch(f"{MODULE}.get_tool_registry", AsyncMock(return_value=registry)),
        patch(
            f"{MODULE}.workflow_executions_repository.find_latest_with_trace",
            AsyncMock(return_value=None),
        ),
        patch(f"{MODULE}.get_subagent_by_id", return_value=subagent),
        patch(f"{MODULE}.ainvoke_structured", llm),
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


def test_the_scripted_model_never_reaches_a_provider() -> None:
    """It answers from the messages alone — no client, no key, no token spend."""
    model = ScriptedModel(script=[ScriptedCall(name="list_events", args={})])

    assert isinstance(model.turn_for([]), AIMessage)
    assert model._llm_type == "playbook-scripted"
