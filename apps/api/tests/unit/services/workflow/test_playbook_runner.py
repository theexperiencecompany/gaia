"""Replaying a playbook: what actually runs, what is refused, and what it costs.

The runner's whole value is that it is cheaper than the agent and still safe, so
the tests defend both halves: every call goes through the HIL gate before the
tool, and one replay makes exactly one model call no matter how many ``$ask``
fields it has to fill.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool

from app.models.playbook_models import PlaybookAsk, PlaybookDocument, PlaybookStep
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import (
    PlaybookAskAnswer,
    PlaybookNarration,
    PlaybookRunResult,
    run_playbook,
)

MODULE = "app.services.workflow.playbook.runner"

USER = PlaybookUser(email="ada@example.com", name="Ada", timezone="Europe/Berlin")


class _Recorder:
    """Collects the calls the tools actually received, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []


def _tools(recorder: _Recorder, *, failing: str | None = None) -> dict[str, BaseTool]:
    @tool
    async def list_events(calendar_id: Annotated[str, "Calendar"]) -> str:
        """List calendar events."""
        recorder.calls.append(("list_events", {"calendar_id": calendar_id}))
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


class _FakeRegistry:
    """The tool registry seam: the runner reads tools from it, never builds them."""

    def __init__(self, tools: dict[str, BaseTool]) -> None:
        self._tools = tools

    def get_tool_dict(self) -> dict[str, BaseTool]:
        return self._tools

    def get_category_of_tool(self, tool_name: str) -> str:
        return "calendar" if tool_name == "list_events" else "mail"


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
        raw_yaml="",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _narration(result: str = "Twelve events, mail sent.", **asks: str) -> PlaybookNarration:
    return PlaybookNarration(
        asks=[PlaybookAskAnswer(name=name, text=text) for name, text in asks.items()],
        result=result,
    )


async def _run(
    playbook: PlaybookDocument,
    registry: _FakeRegistry,
    narration: PlaybookNarration | None = None,
    gate: ToolMessage | None = None,
) -> tuple[PlaybookRunResult, AsyncMock]:
    """Run the playbook with mocked seams; hands back the result and the LLM mock."""
    llm = AsyncMock(return_value=narration or _narration())
    with (
        patch(f"{MODULE}.get_tool_registry", AsyncMock(return_value=registry)),
        patch(
            f"{MODULE}.workflow_executions_repository.find_latest_with_trace",
            AsyncMock(return_value=None),
        ),
        patch(f"{MODULE}.decide_tool_call", AsyncMock(return_value=gate)),
        patch(f"{MODULE}.ainvoke_structured", llm),
    ):
        result = await run_playbook(
            playbook, user=USER, conversation_id="conv_1", trigger={"to": "team@example.com"}
        )
    return result, llm


AGENDA_STEPS = [
    PlaybookStep(id="events", tool="list_events", args={"calendar_id": "primary"}),
    PlaybookStep(id="mail", tool="send_email", args={"to": "$trigger.to"}),
]


async def test_steps_run_in_order_through_the_registry() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, _ = await _run(_playbook(AGENDA_STEPS), registry)

    assert result.ok is True
    assert [name for name, _ in recorder.calls] == ["list_events", "send_email"]
    assert [call.tool_name for call in result.trace] == ["list_events", "send_email"]


async def test_resolved_arguments_reach_the_tool() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    await _run(_playbook(AGENDA_STEPS), registry)

    assert recorder.calls[1][1]["to"] == "team@example.com"


async def test_a_gated_call_is_refused_without_invoking_the_tool() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))
    denial = ToolMessage(content="needs approval", tool_call_id="x", name="list_events")

    result, _ = await _run(_playbook(AGENDA_STEPS), registry, gate=denial)

    assert recorder.calls == []
    assert result.ok is False
    assert "list_events" in (result.failure or "")
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
    assert result.ok is True
    assert recorder.calls[1][1] == {"to": "team@example.com", "body": "Twelve events today."}
    assert result.text == "Twelve events, mail sent."
    assert result.llm_calls == 1


async def test_a_playbook_with_no_asks_still_makes_exactly_one_call() -> None:
    recorder = _Recorder()
    registry = _FakeRegistry(_tools(recorder))

    result, llm = await _run(_playbook(AGENDA_STEPS), registry)

    assert llm.await_count == 1
    assert result.llm_calls == 1


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
