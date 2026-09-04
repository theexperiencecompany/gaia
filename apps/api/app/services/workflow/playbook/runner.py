"""Replay a playbook: run its recorded sequence for real, without a model driving it.

Each step runs inside a real agent graph (``create_agent``) driven by
``ScriptedModel``, which emits the recorded call and nothing else. That is what
makes a replay use the same machinery an agentic run uses — the pregel runtime,
the stream writer, the metadata copy, the middleware stack and the HIL gate —
rather than a hand-supplied imitation of it. What a replay does NOT do is think.
Its model calls are one ask call per step that carries a ``$ask`` slot, plus the
narration at the end that writes the user-facing result and judges the run. Each
ask call fires immediately before its own step, so a slot whose instruction
depends on an earlier step's result is written from that result rather than from
a run that has not reached it yet. The narration is separate from all of them
because the result and the verdict can only be written once every step has run;
a verdict written mid-run judges steps that have not happened yet.

A step is its own graph invocation because a playbook step addresses the results
of the steps before it (``$steps.x.y``), so the call to emit is not known until
its predecessor has answered.

Two properties are load-bearing:

* **Recording is incremental.** Each call lands on the trace as it completes, so a
  run that dies after a side effect still leaves a durable record of what already
  happened. That record is what stops the agent fallback from sending twice.
* **The runner decides nothing else.** A failed step stops the run and comes back
  as a report addressed to the caller. Whether to fall back, notify, or re-arm is
  the worker's call, not this module's.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Literal, cast
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.agents.llm.client import ainvoke_llm, background_structured_runnable, metered_config
from app.agents.middleware.factory import (
    AccountingOptions,
    ContextOptions,
    SubagentStackOptions,
    create_middleware_stack,
)
from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_ASK_PROMPT,
    PLAYBOOK_NARRATION_FALLBACK_TEMPLATE,
    PLAYBOOK_NARRATION_PROMPT,
)
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.agents.workspace.offload import read_offload
from app.constants.hil import HIL_STATUS_KWARG
from app.constants.log_tags import LogTag
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.models.agent_models import AgentConfigurable
from app.models.playbook_models import (
    LocatedAsk,
    PlaybookDocument,
    PlaybookStep,
    ask_slots,
    has_ask_slots,
)
from app.models.workflow_execution_models import (
    RecordedCall,
    build_result_digest,
    largest_list_len,
)
from app.override.langgraph_bigtool.agent_config import AgentConfig, ToolRetrievalConfig
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.utils import State
from app.services.workflow.playbook.evaluator import (
    PlaceholderError,
    PlaybookUser,
    RunContext,
    StepResult,
    fill_ask_slots,
    last_run_index,
    parse_result,
    resolve_args,
)
from app.services.workflow.playbook.scripted_model import ScriptedCall, ScriptedModel
from app.services.workflow.playbook.tool_space import (
    ToolSpace,
    handoff_tool_space,
    resolve_subagent_tools,
    tool_space_denial,
)
from app.utils.timezone import Timezone
from shared.py.wide_events import log

#: How much of a step's result the FAILURE REPORT quotes. Short on purpose: it
#: is read by a person working out which step broke, not used to write anything.
#: Deliberately NOT shared with the narration below. One bound served both once,
#: and at 120 characters the model writing the run's result saw a single JSON
#: value cut mid-token and reported the run as truncated: it was summarising the
#: bound rather than the data.
_FAILURE_QUOTE_MAX_CHARS = 120

#: How much of a step's result the NARRATION reads. The record's bound
#: (RESULT_DIGEST_MAX_CHARS) keeps history from growing with the number of runs;
#: the narration is not history, it is the one reader that writes the user's
#: result from the data, and at the record's 4000 characters it saw three of an
#: inbox's five emails and told the user so. Bounded at all only so a tool that
#: returns megabytes cannot blow the model's context; whole elements are shed,
#: never half of one.
_NARRATION_RESULT_MAX_CHARS = 60_000
#: The arguments a step ran with, as the narration sees them. Seen live: told
#: only the tool name and 20 results, the verdict called a month of read mail
#: "unread, last 24 hours". The args are what it has to judge against.
_NARRATION_ARGS_MAX_CHARS = 400

#: The tool name a handoff node records itself under, matching what the agent
#: path emits for the same delegation.
_HANDOFF_TOOL = "handoff"

#: What a replayed step's graph is metered and logged as.
_REPLAY_AGENT_NAME = "playbook_replay"

#: The labels a failure report gives the run's model calls.
_ASK_FILL_LABEL = "ask_fill"
_NARRATION_LABEL = "narration"

#: A replayed step is one tool call plus the turn that ends the loop. The ceiling
#: exists only so a tool whose result loops the graph cannot run away.
_REPLAY_RECURSION_LIMIT = 8

#: A completed line as a BRIEF quotes it back — the agent's fallback note and the
#: narration fallback the user reads. Both say what ran and roughly what came
#: back; neither needs the whole payload the narration itself was shown.
FALLBACK_LINE_MAX_CHARS = 1_500


class PlaybookAskAnswer(BaseModel):
    """One ``$ask`` slot, written by an ask call."""

    name: str = Field(description="The slot's key, exactly as listed in <asks>")
    text: str = Field(description="What to write for that slot")


class PlaybookAskFill(BaseModel):
    """What one ask call produces: the slots its own step needs, and nothing else."""

    asks: list[PlaybookAskAnswer] = Field(default_factory=list)


class PlaybookNarration(BaseModel):
    """What the end-of-run call produces: the result and a verdict on the steps that ran."""

    result: str = Field(description="The run's user-facing result")

    @field_validator("result")
    @classmethod
    def _says_something(cls, value: str) -> str:
        # Seen live: a narration answered "..." and it was delivered as the run's
        # result. A result with no letter or digit in it is not one; refusing it
        # here makes the call raise, which stops the run and hands it to the agent.
        if not any(ch.isalnum() for ch in value):
            raise ValueError("the result says nothing")
        return value

    outcome: Literal["ok", "suspect"] = Field(
        default="ok",
        description="ok when the results plausibly fulfil the playbook, suspect otherwise",
    )
    reason: str = Field(default="", description="One line on why the run is suspect, else empty")


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
    #: How many real model calls the replay made: one ask fill per step that
    #: carried a slot, plus the end-of-run narration. A call that raised is not
    #: counted.
    llm_calls: int = 0
    #: Why a run that completed (``ok=True``) is not trusted: a step came back
    #: empty where the previous run had items, or the narration judged the
    #: results wrong. Never set on a stopped run, which reports through ``failure``.
    suspect: str | None = None
    #: Which check produced ``suspect``: the deterministic record comparison, or
    #: the narration's own verdict. The worker weighs them differently, so it
    #: needs to know which one spoke. ``None`` exactly when ``suspect`` is.
    suspect_source: Literal["record", "narration"] | None = None
    #: Why the end-of-run call did not write the result, on a run where every
    #: step ran anyway (``ok=True``, ``text`` the fallback record of what ran).
    #: The steps are the workflow; only the sentence about them is missing, so
    #: this is a delivered run, not a playbook to heal.
    narration_failed: str | None = None


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
    previous_trace: Sequence[RecordedCall] = ()
    trace: list[RecordedCall] = field(default_factory=list)
    steps: dict[str, StepResult] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    asks: dict[str, str] = field(default_factory=dict)
    #: The most recent ask call's answers, as the model returned them. ``asks``
    #: is the accumulation across every such call and is what steps read.
    ask_fill: PlaybookAskFill | None = None
    narration: PlaybookNarration | None = None
    #: Real model calls that returned; the replay's cost line.
    llm_calls: int = 0
    #: The first deterministic reason a completed step was not trusted.
    suspect: str | None = None
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
            last_run=last_run_index(previous.trace) if previous is not None else {},
        ),
        configurable=configurable,
        previous_trace=previous.trace if previous is not None else (),
    )
    space = ToolSpace(tools=registry.get_tool_dict(), runtime=None, subagent_id=None)

    failure = await _run_steps(playbook, playbook.steps, run, space)
    if failure is not None:
        return PlaybookRunResult(
            ok=False,
            trace=run.trace,
            completed=run.completed,
            failure=_failure_text(failure, run.completed),
            llm_calls=run.llm_calls,
        )
    if run.suspect is not None:
        # Stopped on the record's word: no narration, nothing to deliver. The
        # agent finishes this fire from the list of what ran.
        return PlaybookRunResult(
            ok=True,
            trace=run.trace,
            completed=run.completed,
            llm_calls=run.llm_calls,
            suspect=run.suspect,
            suspect_source="record",
        )

    narration_failure = await _narrate_or_fail(playbook, run)
    if narration_failure is not None:
        return _narration_fallback(run, narration_failure)

    narration = run.narration
    if narration is None:
        raise RuntimeError("playbook replay finished every step without a narration")
    suspect, suspect_source = _suspect_verdict(run, narration)
    return PlaybookRunResult(
        ok=True,
        text=narration.result,
        trace=run.trace,
        completed=run.completed,
        llm_calls=run.llm_calls,
        suspect=suspect,
        suspect_source=suspect_source,
    )


async def _run_steps(
    playbook: PlaybookDocument,
    steps: Sequence[PlaybookStep],
    run: _Run,
    space: ToolSpace,
) -> _StepFailure | None:
    """Run one level of the playbook in order. The first failure stops everything.

    So does the first step the record shows to be suspect: a fetch that came
    back empty where the previous replay had items is answered by the agent,
    and the steps after it (the send, the create) must not run first on data
    nobody trusts. The agent gets the list of what did run.
    """
    for step in steps:
        run.position += 1
        failure = (
            await _run_handoff(playbook, step, run)
            if step.handoff
            else await _run_tool_step(playbook, step, run, space)
        )
        if failure is not None:
            return failure
        if run.suspect is not None:
            return None
    return None


async def _run_handoff(
    playbook: PlaybookDocument, step: PlaybookStep, run: _Run
) -> _StepFailure | None:
    """Run a handoff's recorded children inside that subagent's tool space."""
    subagent_id = step.handoff or ""
    position = run.position
    space = await _subagent_space(subagent_id, playbook.user_id, run.registry)
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


@dataclass(frozen=True)
class _StepCall:
    """One resolved tool step, as it is about to run: the step, its position
    in the playbook, the tool it names and the arguments after resolution."""

    step: PlaybookStep
    position: int
    tool_name: str
    args: dict[str, Any]


async def _run_tool_step(
    playbook: PlaybookDocument, step: PlaybookStep, run: _Run, space: ToolSpace
) -> _StepFailure | None:
    """Resolve one recorded call and replay it through a graph, then record it."""
    tool_name = step.tool or ""
    position = run.position

    if has_ask_slots(step.args):
        failure = await _fill_asks_or_fail(
            playbook, step, run, pending=_labels(playbook.steps)[position - 1 :]
        )
        if failure is not None:
            return failure

    denial = tool_space_denial(tool_name, space)
    if denial is not None:
        return _StepFailure(position, tool_name, denial)

    try:
        # Slots first, then placeholders: filling turns a slot into an ordinary
        # string, which resolution then scans like any other authored value.
        filled = fill_ask_slots(step.args, run.asks, key_prefix=step.id or tool_name)
        args = resolve_args(filled, _context(run))
    except PlaceholderError as exc:
        return _StepFailure(position, tool_name, exc.message)

    call = _StepCall(step=step, position=position, tool_name=tool_name, args=args)
    answered = await _call_step(playbook, run, space, call)
    if isinstance(answered, _StepFailure):
        return answered
    return _record_step(playbook, run, space, call, answered)


async def _call_step(
    playbook: PlaybookDocument, run: _Run, space: ToolSpace, call: _StepCall
) -> ToolMessage | _StepFailure:
    """Replay the call; the message it produced, or why it produced none."""
    # A raise out of the graph is a stopped step, not a dead run: the steps
    # before it already had their side effects, and only a result that carries
    # the trace lets the worker hand the rest to the agent without repeating them.
    try:
        message = await _replay_call(ScriptedCall(name=call.tool_name, args=call.args), run, space)
    except Exception as exc:
        log.exception(
            f"{LogTag.WORKFLOW} Playbook step raised instead of returning a result",
            playbook_id=playbook.playbook_id,
            workflow_id=playbook.workflow_id,
            tool_name=call.tool_name,
            error_type=type(exc).__name__,
        )
        return _StepFailure(call.position, call.tool_name, f"raised {type(exc).__name__}: {exc}")
    if message is None:
        return _StepFailure(
            call.position, call.tool_name, "the graph produced no result for this call"
        )

    text = message.content if isinstance(message.content, str) else str(message.content)

    # The gate's verdict IS the result: the call was refused and never ran, and a
    # background replay has no live client to ask, so it stays refused.
    # Deliberately not recorded — nothing was attempted, and a trace entry here
    # would tell the next run's `$last_run` that this tool answered.
    if message.additional_kwargs.get(HIL_STATUS_KWARG):
        return _StepFailure(call.position, call.tool_name, f"refused by the approval gate: {text}")
    return message


def _record_step(
    playbook: PlaybookDocument,
    run: _Run,
    space: ToolSpace,
    call: _StepCall,
    message: ToolMessage,
) -> _StepFailure | None:
    """Put the call on the record and read its result; a failure when the
    result is one the run cannot trust or cannot keep."""
    tool_name, position, step = call.tool_name, call.position, call.step
    text = message.content if isinstance(message.content, str) else str(message.content)

    # The record is the run's contract: a call that ran but cannot be recorded
    # stops the run as a report, never as a raise that loses the steps before it.
    try:
        _record(run, tool_name, space.subagent_id, call.args, text)
    except ValidationError as exc:
        log.exception(
            f"{LogTag.WORKFLOW} Playbook step ran but its result could not be recorded",
            playbook_id=playbook.playbook_id,
            workflow_id=playbook.workflow_id,
            tool_name=tool_name,
            error_type=type(exc).__name__,
        )
        return _StepFailure(
            position, tool_name, f"ran, but its result could not be recorded ({exc.title})"
        )
    if message.status == "error":
        return _StepFailure(position, tool_name, text)
    value = parse_result(text)
    # A tool that catches its own failure answers with a success-shaped
    # message carrying an error envelope; that is a failed step, not a result.
    reported = _envelope_failure(value)
    if reported is not None:
        return _StepFailure(position, tool_name, reported)

    if step.id:
        info = read_offload(message)
        run.steps[step.id] = StepResult(value=value, file=info["path"] if info else None)
    if run.suspect is None:
        run.suspect = _empty_where_previous_had_items(tool_name, value, run.previous_trace)
    # This line is the model's only view of what the tool returned, and it has
    # to write the user's result from it: bounded for the model, not the record.
    shown = build_result_digest(text, max_chars=_NARRATION_RESULT_MAX_CHARS)
    run.completed.append(
        f"{step.id or tool_name} ({tool_name} {_shown_args(call.args)}) -> {shown}"
    )
    return None


def _shown_args(args: dict[str, Any]) -> str:
    rendered = json.dumps(args, separators=(",", ":"), default=str)
    if len(rendered) <= _NARRATION_ARGS_MAX_CHARS:
        return rendered
    return rendered[:_NARRATION_ARGS_MAX_CHARS] + "..."


async def _replay_call(call: ScriptedCall, run: _Run, space: ToolSpace) -> ToolMessage | None:
    """Run one recorded call through its own scripted graph; ``None`` if it produced none.

    Everything a tool needs at runtime — the pregel runtime behind
    ``get_stream_writer()``, the middleware chain, the HIL gate and the per-call
    timeout — comes from the graph, exactly as it does for an agent turn. Only
    ``metadata`` is still set by hand, for the same reason ``build_agent_config``
    sets it on every agent run: LangGraph does not derive it from ``configurable``
    and ``get_user_id_from_config`` reads only ``metadata``.

    Retrieval is off because a replay never discovers tools — it runs calls a real
    run already made — so the space's whole tool set is bound from the start. So
    are accounting and summarization: a scripted turn is not a model call and has
    no history to summarize.
    """
    builder = create_agent(
        ScriptedModel(script=[call]),
        space.tools,
        tools_config=ToolRetrievalConfig(
            disable_retrieve_tools=True,
            initial_tool_ids=list(space.tools),
        ),
        agent_config=AgentConfig(
            agent_name=_REPLAY_AGENT_NAME,
            middleware=create_middleware_stack(
                agent_name=_REPLAY_AGENT_NAME,
                chat_llm=None,
                accounting=AccountingOptions(enabled=False),
                context=ContextOptions(summarize=False),
                subagent=SubagentStackOptions(enabled=False),
            ),
        ),
    )
    configurable = _configurable_for(run, space)
    state = cast(
        State,
        await builder.compile().ainvoke(
            cast(State, {"messages": [], "todos": []}),
            config=cast(
                RunnableConfig,
                {
                    "configurable": configurable,
                    "metadata": {"user_id": configurable.get("user_id")},
                    "recursion_limit": _REPLAY_RECURSION_LIMIT,
                },
            ),
        ),
    )
    return next(
        (message for message in reversed(state["messages"]) if isinstance(message, ToolMessage)),
        None,
    )


def _envelope_failure(value: object) -> str | None:
    """What a JSON envelope says went wrong, or ``None`` when it reports no failure."""
    if not isinstance(value, dict):
        return None
    error = value.get("error")
    if value.get("success") is not False and not error:
        return None
    reported = error or value.get("message") or "the tool reported success=false"
    return str(reported)[:_FAILURE_QUOTE_MAX_CHARS]


def _empty_where_previous_had_items(
    tool_name: str, value: object, previous: Sequence[RecordedCall]
) -> str | None:
    """Why an empty result is suspect: the previous run's same tool had items.

    An empty list is a legitimate answer (no mail today) right up until the run
    before it had a full one, at which point it is far more likely a silent
    auth or filter failure than a quiet day. The record is read by tool name,
    LAST match, the same way ``last_run_index`` resolves ``$last_run``: a tool
    called twice in one run is compared against the attempt that worked.
    """
    if largest_list_len(value) != 0:
        return None
    earlier = next(
        (call for call in reversed(previous) if call.tool_name == tool_name and call.replayed),
        None,
    )
    if earlier is None:
        return None
    before = largest_list_len(parse_result(earlier.result_digest))
    if not before:
        return None
    return f"{tool_name} returned no items where the previous run returned {before}"


def _suspect_verdict(
    run: _Run, narration: PlaybookNarration
) -> tuple[str | None, Literal["record", "narration"] | None]:
    """The deterministic reason first; the narration's verdict only fills a gap."""
    if run.suspect is not None:
        return run.suspect, "record"
    if narration.outcome != "suspect":
        return None, None
    return narration.reason or "the narration judged the results suspect", "narration"


def _record(
    run: _Run, tool_name: str, subagent_id: str | None, args: dict[str, Any], text: str
) -> None:
    """Append the call to the trace the moment it resolves.

    Appended before the caller decides what the result means, so a step that
    fails after a side effect is still on the record.
    """
    run.trace.append(
        RecordedCall(
            tool_name=tool_name,
            tool_category=run.registry.get_category_of_tool(tool_name),
            subagent_id=subagent_id,
            args=args,
            result_digest=build_result_digest(text),
            replayed=True,
        )
    )


async def _subagent_space(
    subagent_id: str, user_id: str, registry: ToolRegistry
) -> ToolSpace | None:
    """The tool space a handoff's children run in, or ``None`` for an unknown id."""
    # The same resolution AND the same construction the validator used when this
    # playbook was written. If the two ever diverge, a playbook is accepted and
    # then replayed against a tool space that never had the tool it recorded.
    space = await resolve_subagent_tools(subagent_id, user_id, registry)
    if space is None:
        return None
    return handoff_tool_space(space)


def _configurable_for(run: _Run, space: ToolSpace) -> dict[str, Any]:
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


async def _fill_asks_or_fail(
    playbook: PlaybookDocument, step: PlaybookStep, run: _Run, *, pending: Sequence[str]
) -> _StepFailure | None:
    """Run the ask fill; a raise becomes the failure that stops the run.

    Positioned at the step that needed the asks, so the report says that step
    never ran and what had completed by the time the model call died.
    """
    try:
        await _fill_asks(playbook, step, run, pending=pending)
    except Exception as exc:
        return _model_call_failure(playbook, run, _ASK_FILL_LABEL, exc)
    return None


async def _narrate_or_fail(playbook: PlaybookDocument, run: _Run) -> _StepFailure | None:
    """Run the narration; a raise comes back as the reason it wrote nothing.

    Positioned at the last step, so the reason still says every step had
    completed by the time the model call died. The caller turns it into a
    completed run, not a stopped one — see ``_narration_fallback``.
    """
    try:
        await _narrate(playbook, run)
    except Exception as exc:
        return _model_call_failure(playbook, run, _NARRATION_LABEL, exc)
    return None


def _model_call_failure(
    playbook: PlaybookDocument, run: _Run, label: str, exc: Exception
) -> _StepFailure:
    log.exception(
        f"{LogTag.WORKFLOW} Playbook model call raised",
        playbook_id=playbook.playbook_id,
        workflow_id=playbook.workflow_id,
        call=label,
        error_type=type(exc).__name__,
    )
    return _StepFailure(run.position, label, f"the {label} raised {type(exc).__name__}: {exc}")


async def _fill_asks(
    playbook: PlaybookDocument, step: PlaybookStep, run: _Run, *, pending: Sequence[str]
) -> PlaybookAskFill:
    """The model call for one step's ask slots, made just before that step runs.

    Scoped to ``step`` rather than the whole playbook because a slot's
    instruction may only be answerable from what ran before it ("summarise the
    events fetched above"): filling every slot at the first one would write a
    later step's argument from a run that had not reached it. ``ask_slots`` is
    called with the single step so the keys are spelled by the one rule the
    evaluator looks them back up by. ``pending`` names the steps that have not
    run yet, so the model knows what its answers are about to be used for. The
    result and the verdict are deliberately not written here: they would
    describe a run whose outcome is not known yet.
    """
    located = ask_slots([step])
    config = metered_config(playbook.user_id)
    fill: PlaybookAskFill = await ainvoke_llm(
        background_structured_runnable(PlaybookAskFill, config=config),
        PLAYBOOK_ASK_PROMPT.format(
            description=playbook.description,
            completed="\n".join(run.completed) or "nothing yet",
            remaining="\n".join(pending),
            asks=_render_asks(located),
        ),
        label="playbook_ask_fill",
        config=config,
    )
    run.llm_calls += 1
    run.ask_fill = fill
    # Accumulated, never replaced: an earlier step's filled slots are still
    # part of the arguments its record shows, and the narration reads them all.
    run.asks.update({answer.name: answer.text for answer in fill.asks})
    missing = sorted({ask.key for ask in located} - set(run.asks))
    if missing:
        log.warning(
            f"{LogTag.WORKFLOW} Playbook ask fill wrote nothing for some slots",
            playbook_id=playbook.playbook_id,
            workflow_id=playbook.workflow_id,
            missing_asks=missing,
        )
    return fill


async def _narrate(playbook: PlaybookDocument, run: _Run) -> PlaybookNarration:
    """The end-of-run model call: the user's result and a verdict on what ran.

    Always after the last step, so both are written from the whole run's
    results. The filled asks ride along for context only.
    """
    config = metered_config(playbook.user_id)
    narration: PlaybookNarration = await ainvoke_llm(
        background_structured_runnable(PlaybookNarration, config=config),
        PLAYBOOK_NARRATION_PROMPT.format(
            description=playbook.description,
            completed="\n".join(run.completed) or "nothing",
            asks=_render_filled_asks(run.asks),
            result_brief=playbook.result_brief,
        ),
        label="playbook_narration",
        config=config,
    )
    run.llm_calls += 1
    run.narration = narration
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


def _render_asks(located: Sequence[LocatedAsk]) -> str:
    """The slots to write, as one ask call is shown them.

    One line per slot, keyed exactly as the runner will look the answer back up.
    There is no "works from" line: a slot is filled from everything listed as
    already run, because it has no way to name a subset of it.
    """
    if not located:
        return "none"
    lines: list[str] = []
    for ask in located:
        lines.append(f"- {ask.key}: {ask.slot.prompt}")
        # A per-slot cap cannot be enforced through the API when one call writes
        # several slots, so it is stated to the model as the budget it is.
        lines.append(f"  budget: about {ask.slot.max_tokens} tokens")
    return "\n".join(lines)


def _render_filled_asks(asks: Mapping[str, str]) -> str:
    """The asks as the ask calls wrote them, for the end-of-run call to read."""
    if not asks:
        return "none"
    return "\n".join(f"- {name}: {text}" for name, text in asks.items())


def completed_block(completed: Sequence[str]) -> str:
    """What ran, one bounded line each, as a brief quotes it back to a reader."""
    return "\n".join(f"- {_bounded_line(line)}" for line in completed) or "- nothing"


def _bounded_line(line: str) -> str:
    return line if len(line) <= FALLBACK_LINE_MAX_CHARS else line[:FALLBACK_LINE_MAX_CHARS] + "..."


def _narration_fallback(run: _Run, failure: _StepFailure) -> PlaybookRunResult:
    """Every step ran and only the sentence about them could not be written.

    Prod: 13 of 15 failed replays were exactly this — every tool step complete,
    the narration call alone raising. Reporting that as a stopped run gave the
    user nothing and sent the next fire to a ~20-call heal run against a frozen
    sequence that had just done its job. The steps' own record is a worse result
    than the narration's sentence and a far better one than silence.

    ``suspect`` stays unset: the narration is what produces a verdict, and it
    never spoke. An unwritten verdict is not a clean one.
    """
    return PlaybookRunResult(
        ok=True,
        text=PLAYBOOK_NARRATION_FALLBACK_TEMPLATE.format(
            reason=failure.reason, completed=completed_block(run.completed)
        ),
        trace=run.trace,
        completed=run.completed,
        llm_calls=run.llm_calls,
        narration_failed=failure.reason,
    )


def _failure_text(failure: _StepFailure, completed: Sequence[str]) -> str:
    """The stopped run as a report to the caller, not as an exception."""
    done = (
        "; ".join(line[:_FAILURE_QUOTE_MAX_CHARS] for line in completed) if completed else "nothing"
    )
    return (
        f"Playbook stopped at step {failure.position} ({failure.label}): {failure.reason}. "
        f"Completed: {done}. Nothing after that step ran."
    )
