"""The one place a tool executes, and therefore the one place a call is recorded.

Every path that runs a tool (the graph tool node, the retrieve_tools node, the
execute proxy's dispatch, a sandbox script's callback, an approved action run
later) calls ``invoke_tool``, so the run record holds every call by
construction rather than by each path remembering to report it.
tests/unit/agents/tools/test_tool_invocation_paths.py fails CI on any other
invocation of a tool.

The execute proxy itself is not recorded: its dispatch invokes the real tool
through here, and that real call (name, args, result) is the record.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import cast

from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from app.agents.core.subagents.call_record import is_error_envelope
from app.agents.tools.run_record import append_call, append_call_sync
from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.workflow_execution_models import RecordedCall, build_result_digest, parse_result
from shared.py.wide_events import log

#: How a graph tool node marks its input as a ToolCall rather than plain args.
GRAPH_TOOL_CALL_TYPE = "tool_call"


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
        output = await tool.ainvoke(dict(tool_input), config=config)
    except GraphBubbleUp:
        # A pause for approval, not a finished call: recorded when it resumes and runs.
        raise
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
    """Sync twin of invoke_tool, for LangGraph's sync node functions."""
    pending = _pending(tool, tool_input, config, call_args, None)
    try:
        output = tool.invoke(dict(tool_input), config=config)
    except GraphBubbleUp:
        raise
    except Exception as exc:
        _write_sync(pending, _error_text(exc), failed=True)
        raise
    _write_sync(pending, output)
    return output


async def _write(
    pending: tuple[str, RecordedCall] | None, output: object, *, failed: bool = False
) -> None:
    """Append a finished call to its run's record; a failed write is logged, never raised."""
    if pending is None:
        return
    call = _finished(pending[1], output, failed=failed)
    try:
        await append_call(pending[0], call)
    except Exception as exc:
        # The tool already ran: raising would report it failed and invite a repeat.
        _log_unrecorded(call, exc)


def _write_sync(
    pending: tuple[str, RecordedCall] | None, output: object, *, failed: bool = False
) -> None:
    """Sync twin of _write."""
    if pending is None:
        return
    call = _finished(pending[1], output, failed=failed)
    try:
        append_call_sync(pending[0], call)
    except Exception as exc:
        # The tool already ran: raising would report it failed and invite a repeat.
        _log_unrecorded(call, exc)


def _log_unrecorded(call: RecordedCall, exc: Exception) -> None:
    log.error(
        f"{LogTag.TOOL} run record: a finished call was not recorded",
        tool_name=call.tool_name,
        error_type=type(exc).__name__,
        exc_info=True,
    )


def _pending(
    tool: BaseTool,
    tool_input: Mapping[str, object],
    config: RunnableConfig | None,
    call_args: Mapping[str, object] | None,
    via: ViaExecute | None,
) -> tuple[str, RecordedCall] | None:
    """Return (stream id, the call before its result) for a call that belongs to a run, else None."""
    if tool.name == EXECUTE_TOOL_NAME or config is None:
        return None
    configurable: AgentConfigurable = agent_configurable(config)
    stream_id = configurable.get("stream_id")
    if not stream_id:
        return None
    call = RecordedCall(
        tool_name=tool.name,
        subagent_id=configurable.get("subagent_id"),
        args=_call_args(tool_input) if call_args is None else dict(call_args),
        proxied=via is not None,
        account=via.account if via is not None else None,
    )
    return stream_id, call


def _finished(call: RecordedCall, output: object, *, failed: bool) -> RecordedCall:
    """Return the call with what it returned, or the error it raised."""
    digest = build_result_digest(_as_text(_result_payload(output)))
    return RecordedCall.model_validate(
        {
            **call.model_dump(mode="json"),
            "result_digest": digest,
            # A tool that reports its own failure under a normal return failed all the same.
            "failed": failed or is_error_envelope(parse_result(digest)),
        }
    )


class _GraphToolCall(BaseModel):
    """The two keys that mark a graph ToolCall input and carry its arguments."""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    args: dict[str, object] = Field(default_factory=dict)


class _CommandUpdate(BaseModel):
    """The messages a state-updating tool's Command adds."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    messages: list[object] = Field(default_factory=list)


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
