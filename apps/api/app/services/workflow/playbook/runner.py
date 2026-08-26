"""Replay a playbook: run its recorded sequence for real, without a model driving it.

The steps go through the same tool registry, the same HIL gate and the same
per-call timeout the agent path uses, because a replay is not a simulation: it
sends the email. What it does NOT do is think. There is no graph, no model in the
loop, and exactly one model call in the whole run, which fills every ``$ask``
field and writes the user-facing result in one pass.

Two properties are load-bearing:

* **Recording is incremental.** Each call lands on the trace as it completes, so a
  run that dies after a side effect still leaves a durable record of what already
  happened. That record is what stops the agent fallback from sending twice.
* **The runner decides nothing else.** A failed step stops the run and comes back
  as a report addressed to the caller. Whether to fall back, notify, or re-arm is
  the worker's call, not this module's.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.core.subagents.base_subagent import build_scoped_tool_dict
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.middleware.runtime_adapter import (
    BigtoolToolRuntime,
    create_tool_call_request,
)
from app.agents.prompts.playbook_prompts import PLAYBOOK_NARRATION_PROMPT
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.agents.tools.core.tool_runtime_config import (
    ToolRuntimeConfig,
    build_provider_parent_tool_runtime_config,
)
from app.agents.workspace.offload import pop_offload_descriptor, read_offload
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS, TOOL_TIMEOUT_EXEMPT_TOOLS
from app.constants.log_tags import LogTag
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.models.agent_models import AgentConfigurable
from app.models.playbook_models import PlaybookAsk, PlaybookDocument, PlaybookStep
from app.models.workflow_execution_models import RESULT_DIGEST_MAX_CHARS, RecordedCall
from app.override.langgraph_bigtool.dynamic_tool_node import format_tool_error
from app.override.langgraph_bigtool.utils import State
from app.services.hil.gate import decide_tool_call
from app.services.workflow.playbook.evaluator import (
    PlaceholderError,
    PlaybookUser,
    RunContext,
    StepResult,
    last_run_index,
    parse_result,
    resolve_args,
)
from app.utils.timezone import Timezone
from shared.py.wide_events import log

#: How much of a step's result the failure report and the model prompt quote. Far
#: shorter than the stored digest: these are read by a human or spent as tokens.
_SUMMARY_MAX_CHARS = 120

#: The tool name a handoff node records itself under, matching what the agent
#: path emits for the same delegation.
_HANDOFF_TOOL = "handoff"


class PlaybookAskAnswer(BaseModel):
    """One ``$ask`` field, written by the run's single model call."""

    name: str = Field(description="The ask's name, exactly as the playbook declares it")
    text: str = Field(description="What to write for that field")


class PlaybookNarration(BaseModel):
    """Everything the one model call produces: every ask, plus the result."""

    asks: list[PlaybookAskAnswer] = Field(default_factory=list)
    result: str = Field(description="The run's user-facing result")


class PlaybookRunResult(BaseModel):
    """What a replay leaves behind, whether it finished or stopped partway."""

    ok: bool
    #: The user-facing result. Empty on a stopped run, which reports through
    #: ``failure`` instead.
    text: str = ""
    trace: list[RecordedCall] = Field(default_factory=list)
    #: Addressed to the caller: which step stopped it, on what tool, and why.
    failure: str | None = None
    #: One line per step that actually ran, so a fallback run can be told what it
    #: must not do again.
    completed: list[str] = Field(default_factory=list)
    llm_calls: int = 0


@dataclass(frozen=True, slots=True)
class _ToolSpace:
    """Where a step's tool is looked up, and what that scope allows.

    Top level is the full registry. Inside a handoff it is the subagent's own
    scoped tool set and runtime config, which is the boundary a delegated call
    already had. Reproduced here without building the subagent's graph, since a
    replay has no model for one to serve.
    """

    tools: Mapping[str, BaseTool]
    runtime: ToolRuntimeConfig | None
    subagent_id: str | None


@dataclass(frozen=True, slots=True)
class _ToolOutcome:
    """A tool call that came back: its text, and the file it offloaded to."""

    text: str
    file: str | None


@dataclass(frozen=True, slots=True)
class _StepFailure:
    """Why one step stopped the run."""

    position: int
    label: str
    reason: str


@dataclass
class _Run:
    """Mutable state of one replay, in the order it accumulates."""

    registry: ToolRegistry
    base: RunContext
    configurable: AgentConfigurable
    trace: list[RecordedCall] = field(default_factory=list)
    steps: dict[str, StepResult] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    asks: dict[str, str] = field(default_factory=dict)
    narration: PlaybookNarration | None = None
    position: int = 0


async def run_playbook(
    playbook: PlaybookDocument,
    *,
    user: PlaybookUser,
    conversation_id: str,
    trigger: Mapping[str, object],
) -> PlaybookRunResult:
    """Replay ``playbook`` and report what happened.

    ``trigger`` is the fire's own context (the webhook payload, the batched
    events), addressable as ``$trigger.<path>``.
    """
    registry = await get_tool_registry()
    previous = await workflow_executions_repository.find_latest_with_trace(
        playbook.workflow_id, playbook.user_id
    )
    configurable: AgentConfigurable = {
        "stream_id": f"playbook_{uuid4().hex}",
        "user_id": playbook.user_id,
        "conversation_id": conversation_id,
        "execution_mode": "background",
    }
    run = _Run(
        registry=registry,
        base=RunContext(
            user=user,
            now=datetime.now(Timezone.parse(user.timezone).tzinfo),
            trigger=trigger,
            steps={},
            last_run=last_run_index(previous.trace) if previous is not None else {},
            asks={},
        ),
        configurable=configurable,
    )
    space = _ToolSpace(tools=registry.get_tool_dict(), runtime=None, subagent_id=None)

    failure = await _run_steps(playbook, playbook.steps, run, space)
    if failure is not None:
        return PlaybookRunResult(
            ok=False,
            trace=run.trace,
            completed=run.completed,
            failure=_failure_text(failure, run.completed),
            llm_calls=1 if run.narration is not None else 0,
        )

    narration = run.narration or await _narrate(playbook, run, pending=[])
    return PlaybookRunResult(
        ok=True,
        text=narration.result,
        trace=run.trace,
        completed=run.completed,
        llm_calls=1,
    )


async def _run_steps(
    playbook: PlaybookDocument,
    steps: Sequence[PlaybookStep],
    run: _Run,
    space: _ToolSpace,
) -> _StepFailure | None:
    """Run one level of the playbook in order. The first failure stops everything."""
    for step in steps:
        run.position += 1
        failure = (
            await _run_handoff(playbook, step, run)
            if step.handoff
            else await _run_tool_step(playbook, step, run, space)
        )
        if failure is not None:
            return failure
    return None


async def _run_handoff(
    playbook: PlaybookDocument, step: PlaybookStep, run: _Run
) -> _StepFailure | None:
    """Run a handoff's recorded children inside that subagent's tool space."""
    subagent_id = step.handoff or ""
    position = run.position
    space = await _subagent_space(subagent_id, run.registry)
    if space is None:
        return _StepFailure(position, _HANDOFF_TOOL, f"no subagent named {subagent_id!r} exists")

    run.trace.append(
        RecordedCall(
            tool_name=_HANDOFF_TOOL,
            tool_category=_HANDOFF_TOOL,
            args={"subagent_id": subagent_id},
        )
    )
    return await _run_steps(playbook, step.steps, run, space)


async def _run_tool_step(
    playbook: PlaybookDocument, step: PlaybookStep, run: _Run, space: _ToolSpace
) -> _StepFailure | None:
    """Resolve, gate, execute and record one tool call."""
    tool_name = step.tool or ""
    position = run.position

    if run.narration is None and _addresses_ask(step):
        await _narrate(playbook, run, pending=_labels(playbook.steps)[position - 1 :])

    denial = _tool_space_denial(tool_name, space)
    if denial is not None:
        return _StepFailure(position, tool_name, denial)

    try:
        args = resolve_args(step.args, _context(run))
    except PlaceholderError as exc:
        return _StepFailure(position, tool_name, exc.message)

    call_id = f"pb_{uuid4().hex[:12]}"
    config = cast(RunnableConfig, {"configurable": _configurable_for(run, space)})
    request = create_tool_call_request(
        tool_call={"name": tool_name, "args": args, "id": call_id},
        tool=space.tools[tool_name],
        state=cast(State, {"messages": []}),
        runtime=BigtoolToolRuntime.from_graph_context(
            config=config, tool_name=tool_name, tool_call_id=call_id
        ),
    )

    # The gate's verdict IS the result when it returns one: the call was refused,
    # and a background replay has no live client to ask, so it stays refused.
    # Deliberately not recorded — nothing was attempted, and a trace entry here
    # would tell the next run's `$last_run` that this tool answered.
    blocked = await decide_tool_call(request)
    if blocked is not None:
        return _StepFailure(position, tool_name, f"refused by the approval gate: {blocked.content}")

    outcome = await _invoke(space.tools[tool_name], tool_name, call_id, args, config)
    if isinstance(outcome, str):
        _record(run, tool_name, space.subagent_id, args, outcome)
        return _StepFailure(position, tool_name, outcome)

    digest = _record(run, tool_name, space.subagent_id, args, outcome.text)
    if step.id:
        run.steps[step.id] = StepResult(value=parse_result(outcome.text), file=outcome.file)
    run.completed.append(f"{step.id or tool_name} ({tool_name}) -> {digest[:_SUMMARY_MAX_CHARS]}")
    return None


async def _invoke(
    tool: BaseTool,
    tool_name: str,
    call_id: str,
    args: dict[str, Any],
    config: RunnableConfig,
) -> _ToolOutcome | str:
    """Run one tool under the same timeout the graph applies. A ``str`` IS the error."""
    tool_input: dict[str, Any] = {
        "name": tool_name,
        "args": args,
        "id": call_id,
        "type": "tool_call",
    }
    try:
        if tool_name in TOOL_TIMEOUT_EXEMPT_TOOLS:
            result = await tool.ainvoke(tool_input, config=config)
        else:
            async with asyncio.timeout(TOOL_EXECUTION_TIMEOUT_SECONDS):
                result = await tool.ainvoke(tool_input, config=config)
    except TimeoutError:
        return (
            f"timed out after {TOOL_EXECUTION_TIMEOUT_SECONDS}s; the operation may or may not "
            "have completed on the provider side"
        )
    except Exception as exc:
        return format_tool_error(exc)

    if isinstance(result, Command):
        # A Command is a graph state update. There is no graph here, so applying
        # it is impossible, and treating it as a result would silently drop the
        # tool's whole effect.
        return f"{tool_name} returns a graph state update, which a playbook replay cannot apply"

    if isinstance(result, ToolMessage):
        if result.status == "error":
            return str(result.content)
        info = read_offload(result)
        text = result.content if isinstance(result.content, str) else str(result.content)
    else:
        # A self-offloading tool hands its descriptor back inside a dict result
        # rather than on a message, so it is popped before the rest is read.
        info = pop_offload_descriptor(result)
        text = result if isinstance(result, str) else str(result)
    return _ToolOutcome(text=text, file=info["path"] if info else None)


def _record(
    run: _Run, tool_name: str, subagent_id: str | None, args: dict[str, Any], text: str
) -> str:
    """Append the call to the trace the moment it resolves, and return its digest.

    Appended before the caller decides what the result means, so a step that
    fails after a side effect is still on the record.
    """
    digest = text[:RESULT_DIGEST_MAX_CHARS]
    run.trace.append(
        RecordedCall(
            tool_name=tool_name,
            tool_category=run.registry.get_category_of_tool(tool_name),
            subagent_id=subagent_id,
            args=args,
            result_digest=digest,
        )
    )
    return digest


async def _subagent_space(subagent_id: str, registry: ToolRegistry) -> _ToolSpace | None:
    """The tool space a handoff's children run in, or ``None`` for an unknown id."""
    subagent = get_subagent_by_id(subagent_id)
    if subagent is None:
        return None

    config = subagent.config
    scoped, initial = build_scoped_tool_dict(
        tool_registry=registry,
        tool_space=config.tool_space,
        mcp_tools=None,
        include_finish_task=config.include_finish_task,
    )
    runtime = build_provider_parent_tool_runtime_config(
        provider_tool_names=initial,
        todo_tool_names=[],
        auto_bind_tool_names=config.auto_bind_tools,
        use_direct_tools=config.use_direct_tools,
        disable_retrieve_tools=config.disable_retrieve_tools,
        include_finish_task=config.include_finish_task,
    )
    if subagent.mcp_config is not None:
        # An MCP subagent's real tools live on the user's own MCPClient and never
        # in the global registry, so the scoped set built above would be missing
        # exactly the tools the playbook recorded. Fall back to the registry; the
        # gate stays the boundary either way.
        return _ToolSpace(tools=registry.get_tool_dict(), runtime=runtime, subagent_id=subagent.id)
    return _ToolSpace(tools=scoped, runtime=runtime, subagent_id=subagent.id)


def _tool_space_denial(tool_name: str, space: _ToolSpace) -> str | None:
    """Why this space may not run ``tool_name``, or ``None`` when it may."""
    if tool_name not in space.tools:
        return f"no tool named {tool_name!r} is available in this run's tool space"
    runtime = space.runtime
    if (
        runtime is not None
        and not runtime.enable_retrieve_tools
        and tool_name not in runtime.initial_tool_names
    ):
        return f"{tool_name} is outside the bound tool set of this handoff, which cannot retrieve"
    return None


def _configurable_for(run: _Run, space: _ToolSpace) -> dict[str, Any]:
    """The run's configurable, tagged with the subagent when inside a handoff."""
    configurable: dict[str, Any] = dict(run.configurable)
    if space.subagent_id is not None:
        configurable["subagent_id"] = space.subagent_id
    return configurable


def _context(run: _Run) -> RunContext:
    """The run's fixed context plus everything it has produced so far."""
    base = run.base
    return RunContext(
        user=base.user,
        now=base.now,
        trigger=base.trigger,
        steps=run.steps,
        last_run=base.last_run,
        asks=run.asks,
    )


def _addresses_ask(step: PlaybookStep) -> bool:
    """Whether this step's arguments address a ``$ask`` field."""
    return any("$ask." in text for text in _strings(step.args))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


async def _narrate(
    playbook: PlaybookDocument, run: _Run, *, pending: Sequence[str]
) -> PlaybookNarration:
    """The run's ONE model call: every ask and the result, together.

    They are one call because they read the same material (what the run did) and
    differ only in what they write from it. Two calls would send that material
    twice and double the token cost of every replay. ``pending`` names the steps
    that have not run yet, so a result written mid-run still describes the whole
    run rather than the part that happens to be finished.
    """
    narration = await ainvoke_structured(
        PlaybookNarration,
        PLAYBOOK_NARRATION_PROMPT.format(
            description=playbook.description,
            completed="\n".join(run.completed) or "nothing yet",
            remaining="\n".join(pending) or "nothing, every step has run",
            asks=_render_asks(playbook.ask, run.completed),
            synthesize=playbook.synthesize,
        ),
        label="playbook_narration",
        config=metered_config(playbook.user_id),
    )
    run.narration = narration
    run.asks = {answer.name: answer.text for answer in narration.asks}
    missing = sorted(set(playbook.ask) - set(run.asks))
    if missing:
        log.warning(
            f"{LogTag.WORKFLOW} Playbook narration wrote nothing for declared asks",
            playbook_id=playbook.playbook_id,
            workflow_id=playbook.workflow_id,
            missing_asks=missing,
        )
    return narration


def _labels(steps: Sequence[PlaybookStep]) -> list[str]:
    """Every node in execution order, flattened the same way positions count."""
    labels: list[str] = []
    for step in steps:
        if step.handoff:
            labels.append(f"{_HANDOFF_TOOL} to {step.handoff}")
            labels.extend(_labels(step.steps))
        else:
            labels.append(f"{step.id or step.tool} ({step.tool})")
    return labels


def _render_asks(asks: Mapping[str, PlaybookAsk], completed: Sequence[str]) -> str:
    if not asks:
        return "none"
    lines: list[str] = []
    for name, ask in asks.items():
        lines.append(f"- {name}: {ask.prompt}")
        # A per-field cap cannot be enforced through the API when one call writes
        # every field, so it is stated to the model as the budget it is.
        lines.append(f"  budget: about {ask.max_tokens} tokens")
        seen = [line for line in completed if any(line.startswith(f"{u} (") for u in ask.uses)]
        if seen:
            lines.append(f"  works from: {'; '.join(seen)}")
    return "\n".join(lines)


def _failure_text(failure: _StepFailure, completed: Sequence[str]) -> str:
    """The stopped run as a report to the caller, not as an exception."""
    done = "; ".join(completed) if completed else "nothing"
    return (
        f"Playbook stopped at step {failure.position} ({failure.label}): {failure.reason}. "
        f"Completed: {done}. Nothing after that step ran."
    )
