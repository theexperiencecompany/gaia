"""The one place a tool executes, and therefore the one place a call is recorded.

Every path that runs a tool (the graph tool node, the retrieve_tools node, the
execute proxy's dispatch, a sandbox script's callback, an approved action run
later) calls ``invoke_tool``, so the records hold every call by construction
rather than by each path remembering to report it. Two records are written: the
workflow run record (Redis, what a playbook replays) and, for every executor run,
the run trace (Mongo, app.services.executor_trace).
tests/unit/agents/tools/test_tool_invocation_paths.py fails CI on any other
invocation of a tool.

The execute proxy itself is not recorded: its dispatch invokes the real tool
through here, and that real call (name, args, result) is the record.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import cast

from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from app.agents.core.subagents.call_record import is_error_envelope
from app.agents.tools.run_record import (
    append_call,
    append_call_sync,
    is_integration_blocked,
    is_integration_blocked_sync,
)
from app.agents.tools.tool_integration import tool_integration_id
from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.integrations import ConnectMode
from app.constants.log_tags import LogTag
from app.models.agent_config import read_agent_configurable
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.workflow_execution_models import RecordedCall, build_result_digest, parse_result
from app.services.executor_trace.metrics import TraceWrite, count_trace_write_failed
from app.services.executor_trace.recorder import RunOwner, TracedCall, record_call
from app.services.integrations.integration_resolver import IntegrationResolver
from app.utils.errors import IntegrationNotConnectedError
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log

#: How a graph tool node marks its input as a ToolCall rather than plain args.
GRAPH_TOOL_CALL_TYPE = "tool_call"

RUN_RECORD_NOT_WRITTEN = f"{LogTag.TOOL} run record: a finished call was not recorded"
RUN_TRACE_NOT_WRITTEN = f"{LogTag.TOOL} run trace: a finished call was not recorded"


@dataclass(frozen=True, slots=True)
class ViaExecute:
    """A call the execute proxy dispatched, as the account it named (None: the primary)."""

    account: str | None


async def invoke_tool(
    tool: BaseTool,
    tool_input: Mapping[str, object],
    config: RunnableConfig | None = None,
    *,
    call_args: Mapping[str, object] | None = None,
    via: ViaExecute | None = None,
) -> object:
    """Run tool and record the call in the run it belongs to.

    call_args is what the model asked for, when tool_input also carries values
    the caller injected (a store, the user id); it defaults to tool_input's own args.
    via says the execute proxy dispatched it, which a replay must do again.
    """
    pending = _pending(tool, tool_input, config, call_args, via)
    try:
        blocked = _blocked_run(tool, config)
        if blocked is not None and await is_integration_blocked(*blocked):
            raise IntegrationBlockedError(blocked[1])
        output = await tool.ainvoke(dict(tool_input), config=config)
    except GraphBubbleUp:
        # A pause for approval, not a finished call: recorded when it resumes and runs.
        raise
    except IntegrationNotConnectedError as exc:
        # Only the user can fix it: show the connect card (which blocks the
        # integration for the run) and answer the call with the instruction.
        prompt = await _connect_prompt(exc, config)
        await _write(pending, prompt, failed=True)
        return _as_tool_output(tool, tool_input, prompt)
    except Exception as exc:
        await _write(pending, _error_text(exc), failed=True)
        raise
    await _write(pending, output)
    return output


def invoke_tool_sync(
    tool: BaseTool,
    tool_input: Mapping[str, object],
    config: RunnableConfig | None = None,
    *,
    call_args: Mapping[str, object] | None = None,
) -> object:
    """Sync twin of invoke_tool, for LangGraph's sync node functions.

    Writes the workflow run record only: the run trace's store is async, and no graph
    runs through its sync entry points.
    """
    pending = _pending(tool, tool_input, config, call_args, None)
    try:
        blocked = _blocked_run(tool, config)
        if blocked is not None and is_integration_blocked_sync(*blocked):
            raise IntegrationBlockedError(blocked[1])
        output = tool.invoke(dict(tool_input), config=config)
    except GraphBubbleUp:
        raise
    except Exception as exc:
        _write_sync(pending, _error_text(exc), failed=True)
        raise
    _write_sync(pending, output)
    return output


class IntegrationBlockedError(Exception):
    """A call to an integration this run already asked the user to connect; it was not sent."""

    def __init__(self, integration_id: str) -> None:
        super().__init__(
            f"'{integration_id}' is not connected and the user was already shown how to connect "
            f"it this run, so this call was not sent. Do not call {integration_id} again this "
            "run; finish the rest of the task and say what is waiting on the connection."
        )


def _blocked_run(tool: BaseTool, config: RunnableConfig | None) -> tuple[str, str] | None:
    """Return (stream id, integration id) to check a call against, or None when it has neither."""
    if config is None:
        return None
    stream_id = read_agent_configurable(config).stream_id
    if not stream_id:
        return None
    integration_id = tool_integration_id(tool)
    return (stream_id, integration_id) if integration_id is not None else None


async def _connect_prompt(exc: IntegrationNotConnectedError, config: RunnableConfig | None) -> str:
    """Show the connect card for the integration the call needed and return its instruction."""
    user_id = read_agent_configurable(config).user_id
    if not user_id:
        # No user behind the run (a trigger option lookup): nobody to show a card to.
        return str(exc)
    name = exc.integration_name
    if name is None:
        # An MCP tool knows only its server's id; the card names the integration.
        resolved = await IntegrationResolver.resolve(exc.integration_id)
        name = resolved.name if resolved else exc.integration_id
    return await request_integration_connection(
        exc.integration_id,
        name,
        user_id,
        mode=ConnectMode.RECONNECT if exc.grant_died else ConnectMode.CONNECT,
    )


def _as_tool_output(tool: BaseTool, tool_input: Mapping[str, object], text: str) -> object:
    """Answer in the shape the caller expects: a ToolMessage for a graph ToolCall, else the text."""
    call = _GraphToolCall.model_validate(dict(tool_input))
    if call.type != GRAPH_TOOL_CALL_TYPE:
        return text
    return ToolMessage(content=text, tool_call_id=call.id or "", name=tool.name, status="error")


@dataclass(frozen=True, slots=True)
class _Pending:
    """A call that has started and is recorded when it finishes, in every record it belongs to."""

    tool_name: str
    tool_call_id: str | None
    args: dict[str, object]
    started_at: datetime
    #: The workflow run's stream id and the call before its result; None outside a workflow run.
    workflow_call: tuple[str, RecordedCall] | None
    #: The executor run whose trace holds the call; None when it belongs to no executor run.
    owner: RunOwner | None


@dataclass(frozen=True, slots=True)
class _Outcome:
    """What a finished call returned, as text and as the digest a replay resolves against."""

    text: str
    digest: str
    failed: bool


async def _write(pending: _Pending | None, output: object, *, failed: bool = False) -> None:
    """Record a finished call in each record it belongs to; building or writing a record never raises."""
    if pending is None:
        return
    finished_at = datetime.now(UTC)
    try:
        outcome = _outcome(output, failed=failed)
    except Exception as exc:
        # The tool already ran: raising would report it failed and invite a repeat.
        _log_unrecorded(RUN_RECORD_NOT_WRITTEN, pending.tool_name, exc)
        return
    if pending.workflow_call is not None:
        stream_id, call = pending.workflow_call
        try:
            await append_call(stream_id, _finished(call, outcome))
        except Exception as exc:
            _log_unrecorded(RUN_RECORD_NOT_WRITTEN, pending.tool_name, exc)
    if pending.owner is not None:
        try:
            await record_call(pending.owner, _traced(pending, outcome, finished_at))
        except Exception as exc:
            # Same: the call ran, and the trace is not what decides whether it did.
            count_trace_write_failed(TraceWrite.CALL)
            _log_unrecorded(RUN_TRACE_NOT_WRITTEN, pending.tool_name, exc)


def _write_sync(pending: _Pending | None, output: object, *, failed: bool = False) -> None:
    """Sync twin of _write, for the workflow run record."""
    if pending is None or pending.workflow_call is None:
        return
    stream_id, call = pending.workflow_call
    try:
        append_call_sync(stream_id, _finished(call, _outcome(output, failed=failed)))
    except Exception as exc:
        # The tool already ran: raising would report it failed and invite a repeat.
        _log_unrecorded(RUN_RECORD_NOT_WRITTEN, pending.tool_name, exc)


def _log_unrecorded(message: str, tool_name: str, exc: Exception) -> None:
    log.error(
        message,
        tool_name=tool_name,
        error_type=type(exc).__name__,
        exc_info=True,
    )


def _pending(
    tool: BaseTool,
    tool_input: Mapping[str, object],
    config: RunnableConfig | None,
    call_args: Mapping[str, object] | None,
    via: ViaExecute | None,
) -> _Pending | None:
    """Return the call before its result when a record wants it, else None (the execute proxy, a bare lookup)."""
    if tool.name == EXECUTE_TOOL_NAME or config is None:
        return None
    configurable: AgentConfigurable = agent_configurable(config)
    stream_id = configurable.get("stream_id")
    args = _call_args(tool_input) if call_args is None else dict(call_args)
    # Only a workflow run reads its record back, so only its calls carry what a replay needs.
    workflow_call = (
        (
            stream_id,
            RecordedCall(
                tool_name=tool.name,
                subagent_id=configurable.get("subagent_id"),
                args=args,
                proxied=via is not None,
                account=via.account if via is not None else None,
            ),
        )
        if stream_id and configurable.get("workflow_id")
        else None
    )
    owner = RunOwner.from_config(config)
    if workflow_call is None and owner is None:
        return None
    return _Pending(
        tool_name=tool.name,
        tool_call_id=_tool_call_id(tool_input),
        args=args,
        started_at=datetime.now(UTC),
        workflow_call=workflow_call,
        owner=owner,
    )


def _outcome(output: object, *, failed: bool) -> _Outcome:
    """Read a call's result as text and digest, and whether the call failed."""
    text = _as_text(_result_payload(output))
    digest = build_result_digest(text)
    return _Outcome(
        text=text,
        digest=digest,
        # A tool that reports its own failure under a normal return failed all the same,
        # whether it answered with an error envelope or its own handle_tool_error.
        failed=failed
        or (isinstance(output, ToolMessage) and output.status == "error")
        or is_error_envelope(parse_result(digest)),
    )


def _finished(call: RecordedCall, outcome: _Outcome) -> RecordedCall:
    """Return the call with what it returned, or the error it raised."""
    return RecordedCall.model_validate(
        {**call.model_dump(mode="json"), "result_digest": outcome.digest, "failed": outcome.failed}
    )


def _traced(pending: _Pending, outcome: _Outcome, finished_at: datetime) -> TracedCall:
    return TracedCall(
        tool_name=pending.tool_name,
        tool_call_id=pending.tool_call_id,
        args=pending.args,
        output_text=outcome.text,
        failed=outcome.failed,
        started_at=pending.started_at,
        finished_at=finished_at,
    )


class _GraphToolCall(BaseModel):
    """The two keys that mark a graph ToolCall input and carry its arguments."""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    id: str | None = None
    args: dict[str, object] = Field(default_factory=dict)


class _CommandUpdate(BaseModel):
    """The messages a state-updating tool's Command adds."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    messages: list[object] = Field(default_factory=list)


def _tool_call_id(tool_input: Mapping[str, object]) -> str | None:
    """Return the id the model gave the call when it arrived as a graph ToolCall."""
    call = _GraphToolCall.model_validate(dict(tool_input))
    return call.id if call.type == GRAPH_TOOL_CALL_TYPE else None


def _call_args(tool_input: Mapping[str, object]) -> dict[str, object]:
    """Return the arguments the tool ran with: a graph ToolCall carries them under args."""
    call = _GraphToolCall.model_validate(dict(tool_input))
    return call.args if call.type == GRAPH_TOOL_CALL_TYPE else dict(tool_input)


def _result_payload(output: object) -> object:
    """Return what the model read back: a ToolMessage's content, or the one a Command carries."""
    if isinstance(output, ToolMessage):
        return output.content
    if isinstance(output, Command):
        update = output.update
        if not isinstance(update, Mapping):
            return ""
        messages = _CommandUpdate.model_validate(dict(update)).messages
        answers = [m.content for m in messages if isinstance(m, ToolMessage)]
        return answers[0] if answers else ""
    return output


def _as_text(payload: object) -> str:
    """Return a result as text: structured results as JSON, which $last_run paths and checks parse."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, default=str, ensure_ascii=False)


def _error_text(exc: Exception) -> str:
    return f"Error: {type(exc).__name__}: {exc}"


class RecordingTool(BaseTool):
    """A tool handed to code that invokes tools itself (LangGraph's ToolNode), so the call still records.

    LangGraph injects state into the call and then calls ``tool.ainvoke``; this
    stands in for the real tool there and runs it through invoke_tool, recording
    the model's own args rather than the injected ones.
    """

    inner: BaseTool
    model_args: dict[str, object]

    @classmethod
    def wrapping(cls, inner: BaseTool, model_args: Mapping[str, object]) -> "RecordingTool":
        return cls(
            name=inner.name,
            description=inner.description,
            args_schema=inner.args_schema,
            return_direct=inner.return_direct,
            response_format=inner.response_format,
            inner=inner,
            model_args=dict(model_args),
        )

    async def ainvoke(
        self,
        input: str | dict[str, object] | ToolCall,  # noqa: A002 -- BaseTool's own parameter name
        config: RunnableConfig | None = None,
        **_kwargs: object,
    ) -> object:
        return await invoke_tool(self.inner, _mapping(input), config, call_args=self.model_args)

    def invoke(
        self,
        input: str | dict[str, object] | ToolCall,  # noqa: A002 -- BaseTool's own parameter name
        config: RunnableConfig | None = None,
        **_kwargs: object,
    ) -> object:
        return invoke_tool_sync(self.inner, _mapping(input), config, call_args=self.model_args)

    def _run(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError("RecordingTool runs only through invoke/ainvoke")


def _mapping(tool_input: str | dict[str, object] | ToolCall) -> Mapping[str, object]:
    if isinstance(tool_input, str):
        raise TypeError("a recorded tool call takes structured input, not a bare string")
    return cast(Mapping[str, object], tool_input)
