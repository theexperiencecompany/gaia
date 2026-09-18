"""Check a playbook against the live tool registry, and render it for reading.

validate_playbook asks whether an authored document could actually run: the
tools exist, their args are real, and every reference resolves. Messages
name the offending step and what would be valid, not just "invalid".

Given the authoring run's own results, it also checks whether those calls
actually happened and returned what the document claims — a playbook can
freeze a call that ran but never really produced what it references.

dump_playbook renders a body as YAML for humans; the structured body is the
only stored form, so nothing parses the YAML back.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError
import yaml

from app.agents.core.subagents.call_record import ARG_TRUNCATION_MARKER, is_error_envelope
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.models.playbook_models import (
    TIME_KEY,
    AskSlot,
    ForEachStep,
    HandoffStep,
    PlaybookBody,
    PlaybookStep,
    TimeSlot,
    ToolStep,
    is_ask_slot,
    is_time_slot,
    walk_ask_slots,
)
from app.models.workflow_execution_models import carries_no_data
from app.services.workflow.playbook.evaluator import (
    NO_ITEM,
    STEP_FILE_FIELD,
    PlaceholderError,
    StepResult,
    resolve_item,
    resolve_step,
)
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN, placeholder_tokens
from app.services.workflow.playbook.time_layouts import (
    ISO_DATE_LAYOUT,
    ISO_DATETIME_LAYOUT,
    detect_layout,
)
from app.services.workflow.playbook.tool_space import (
    ToolSpace,
    handoff_tool_space,
    resolve_subagent_tools,
    tool_space_denial,
)

_JSON_TYPE_TO_PYTHON: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


#: Most keys a refusal lists back from a result. Enough to recognise the shape
#: the tool actually returns, short enough that a wide envelope does not bury
#: the sentence that says what is wrong.
_MAX_LISTED_KEYS = 12

#: Longest rendering of a matched call's args inside a message. The args are
#: there to say WHICH call came back empty, not to reproduce it.
_ARGS_IN_MESSAGE_MAX_CHARS = 200


@dataclass(frozen=True, slots=True)
class RecordedResult:
    """One call the authoring run made, with what it actually returned.

    result is parsed the way the replay parses a result (JSON when it is
    JSON, the raw text otherwise), so a check here reads exactly the value a
    $steps placeholder would resolve against at replay.
    """

    tool_name: str
    args: Mapping[str, Any]
    result: object
    #: The stable id of the subagent that made the call (``todos``), or
    #: ``None`` for the executor's own — a step inside ``handoff: todos``
    #: is matched only against that subagent's calls.
    subagent: str | None = None


#: The authoring run's calls, in call order. The order IS part of the matching
#: rule — the last call wins — so a mapping keyed by tool name would lose it.
RunResults = Sequence[RecordedResult]


class PlaybookIssue(BaseModel):
    """One reason a parsed playbook cannot run, addressed to its author."""

    where: str = Field(description="Path to the offending node, e.g. steps[1].args.to")
    problem: str = Field(description="What is wrong and what would be valid instead")


class PlaybookValidation(BaseModel):
    """The verdict on a parsed playbook. ``issues`` is empty exactly when valid."""

    valid: bool
    issues: list[PlaybookIssue] = Field(default_factory=list)


def dump_playbook(body: PlaybookBody) -> str:
    """Serialize a playbook body to the YAML document the agent reads and edits.

    Keys come out in authored order and unset optional keys are left out
    entirely, so a playbook reads like something a person wrote rather than a
    dump of every model field.
    """
    document: dict[str, Any] = {
        "description": body.description,
        "steps": [step.to_document() for step in body.steps],
    }
    # Args are dumped as authored, so an inline ask slot renders as a nested
    # ``$ask:`` mapping right where its value belongs — which is exactly how the
    # agent should read it back when it revises the playbook.
    document["result_brief"] = body.result_brief
    # sort_keys=False and sort_keys=None are byte-identical to PyYAML (it only
    # tests truthiness), so that mutation is provably equivalent and exempt.
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)  # pragma: no mutate


async def validate_playbook(
    body: PlaybookBody, user_id: str, results: RunResults | None = None
) -> PlaybookValidation:
    """Check a parsed playbook against the tools it would actually reach.

    Fatal always: unknown tool, bad arg, or forward step reference. user_id
    matters since tool existence is per-user (handoff subagent space, per-user
    MCP tools). With results (the run's real calls), also flags an unused
    tool, an empty/errored frozen call, or a bad $steps shape.
    """
    registry = await get_tool_registry()
    walk = _Walk(user_id=user_id, registry=registry, results=results)
    await _check_steps(
        body.steps,
        "steps",
        ToolSpace(tools=registry.get_tool_dict(), runtime=None, subagent_id=None),
        walk,
    )
    return PlaybookValidation(valid=not walk.issues, issues=walk.issues)


@dataclass
class _Walk:
    """What one pass over the document accumulates, in document order."""

    user_id: str
    registry: ToolRegistry
    declared_steps: set[str] = field(default_factory=set)
    #: The declared ids that are handoffs. A handoff records no result of its
    #: own, so ``$steps.<handoff>...`` never resolves — seen live as
    #: ``$steps.sweep.list.todos`` being accepted, then stopping the replay.
    handoff_ids: set[str] = field(default_factory=set)
    issues: list[PlaybookIssue] = field(default_factory=list)
    #: The authoring run's calls, or ``None`` when there is no run to check
    #: against. ``None`` and an empty run are different: an empty run means
    #: every tool step froze a call that never happened.
    results: RunResults | None = None
    #: What each declared step returned in that run, filled as the walk passes
    #: the step. A ``$steps`` reference is checked against this, so it can only
    #: ever read a step that ran before it — the same rule the replay enforces.
    step_results: dict[str, StepResult] = field(default_factory=dict)
    #: Positions in ``results`` that a step has already frozen. A recorded call
    #: is one call; two steps matched to it would replay it twice and double a
    #: side effect the run performed once.
    consumed: set[int] = field(default_factory=set)
    #: The subagent whose steps are being walked, ``None`` at the top level.
    scope: str | None = None


async def _check_steps(
    steps: Sequence[PlaybookStep],
    path: str,
    space: ToolSpace,
    walk: _Walk,
) -> None:
    """Walk the steps in document order so a reference can only resolve backwards.

    declared_steps holds exactly what ran before this node. Descending into a
    handoff switches tool space, exactly as the replay does. Checking a
    subagent's children against the executor's registry refuses every
    integration whose tools are fetched per user.
    """
    for index, step in enumerate(steps):
        here = f"{path}[{index}]"
        if not isinstance(step, HandoffStep):
            _check_tool_step(step, here, space, walk)
        else:
            if step.id:
                walk.handoff_ids.add(step.id)
            subagent = await resolve_subagent_tools(step.handoff, walk.user_id, walk.registry)
            if subagent is None:
                walk.issues.append(
                    PlaybookIssue(
                        where=here,
                        problem=f"no subagent named {step.handoff!r} exists to hand off to",
                    )
                )
            else:
                # Playbooks are one level deep, so the scope outside a handoff
                # is always the executor's own.
                walk.scope = step.handoff
                await _check_steps(step.steps, f"{here}.steps", handoff_tool_space(subagent), walk)
                walk.scope = None
        if step.id:
            # The runner keys its record on the id, so a second step with the
            # same id would overwrite the first's result for every later $steps.
            if step.id in walk.declared_steps:
                walk.issues.append(
                    PlaybookIssue(
                        where=here,
                        problem=f"step id {step.id!r} is already used by an earlier step; "
                        "ids must be unique so $steps references and the run's record "
                        "point at one step",
                    )
                )
            walk.declared_steps.add(step.id)


def _check_tool_step(
    step: ToolStep | ForEachStep, path: str, space: ToolSpace, walk: _Walk
) -> None:
    tool_name = step.tool
    denial = tool_space_denial(tool_name, space)
    if denial is not None:
        walk.issues.append(PlaybookIssue(where=path, problem=denial))
        return

    # Matched within the walk's scope: a top-level step against the executor's
    # own calls, a handoff's child against that subagent's — seen live as
    # $item.todo_id accepted over elements carrying id, then stopping the replay.
    recorded = (
        _check_recorded_call(step, tool_name, path, walk) if walk.results is not None else None
    )

    sample = _check_for_each_source(step, path, walk) if isinstance(step, ForEachStep) else NO_ITEM
    schema: dict[str, Any] = space.tools[tool_name].args
    _check_required_args(step, tool_name, path, space, walk)
    for key, value in step.args.items():
        where = f"{path}.args.{key}"
        # ensure_ascii=False, or the marker's ellipsis leaves json.dumps as
        # a \\u2026 escape and this check can never fire. Seen exactly so:
        # the recorded-stub refusal below was dead until this run.
        if ARG_TRUNCATION_MARKER in json.dumps(value, default=str, ensure_ascii=False):
            # The call record cuts long args to keep the record small and marks
            # the cut; a step copied from it would send the stub forever.
            walk.issues.append(
                PlaybookIssue(
                    where=where,
                    problem=(
                        f"{key!r} was cut short in the call record; pass the full value "
                        "you actually sent, not the recorded stub"
                    ),
                )
            )
            continue
        arg_schema = schema.get(key)
        if arg_schema is None:
            walk.issues.append(
                PlaybookIssue(
                    where=where,
                    problem=f"{step.tool} takes no arg {key!r}; it takes: "
                    f"{', '.join(sorted(schema)) or 'nothing'}",
                )
            )
            continue
        # The evaluator's own scanner, so a placeholder embedded in text
        # ("Email $steps.mail.to") is checked exactly as a whole-value one is.
        if is_time_slot(value):
            _check_time_slot(value, key, where, recorded, walk)
            continue
        arg_tokens = list(placeholder_tokens(value))
        for token in arg_tokens:
            _check_placeholder(
                token, where, walk, in_for_each=isinstance(step, ForEachStep), sample=sample
            )
        if any(t.group("root") in _TIME_ROOTS for t in arg_tokens):
            _check_time_layout(value, arg_tokens, key, where, recorded, walk)
        slots = [slot for _, slot in walk_ask_slots(value)]
        if slots and not step.id:
            # A slot is addressed by its step's id; without one it falls back to
            # the tool name, and two id-less steps of the same tool would then
            # share a key and receive one text between them.
            walk.issues.append(
                PlaybookIssue(
                    where=where,
                    problem=f"a step carrying an $ask slot needs an id; give this "
                    f"{step.tool} step one so the slot has an address of its own",
                )
            )
        for slot in slots:
            _check_ask_slot(slot, where, walk)
        # An arg that is (or contains) a reference has no fixed type to check:
        # what the tool receives is whatever the placeholder resolves to or the
        # text a model writes, neither of which exists yet.
        if not arg_tokens and not slots:
            _check_value_type(value, arg_schema, where, walk.issues)


def _check_recorded_call(
    step: ToolStep | ForEachStep, tool_name: str, path: str, walk: _Walk
) -> RecordedResult | None:
    """Check one tool step against the call it froze in the run writing it.

    Matching the step back to a recorded call is also what makes the $steps
    references checkable: the matched result is what later steps read from.
    """
    matched = _matched_call(step, walk)
    if matched is None:
        walk.issues.append(PlaybookIssue(where=path, problem=_unmatched_problem(tool_name, walk)))
        return None
    index, call = matched
    walk.consumed.add(index)
    if step.id:
        walk.step_results[step.id] = StepResult(value=call.result)
    refusal = _result_refusal(tool_name, call)
    if refusal is not None:
        walk.issues.append(PlaybookIssue(where=path, problem=refusal))
    return call


def _unmatched_problem(tool_name: str, walk: _Walk) -> str:
    """Return why no recorded call answers to this step: none made, all frozen already, or only calls with other args."""
    same_tool = [
        (index, call)
        for index, call in enumerate(walk.results or ())
        if call.tool_name == tool_name and call.subagent == walk.scope
    ]
    if not same_tool:
        return (
            f"{tool_name} did not run in this run; a playbook freezes calls "
            "that ran and produced their result. Run it, or drop the step"
        )
    left = [call for index, call in same_tool if index not in walk.consumed]
    if not left:
        return (
            f"{tool_name} ran {len(same_tool)} time(s) in this run and earlier steps froze "
            "every one of them; a step cannot replay a call the run did not make. Drop "
            "this step, or run it again"
        )
    return (
        f"{tool_name} ran {len(same_tool)} time(s) in this run, but never with these args "
        f"(the last call used {_rendered_args(left[-1].args)}); freeze the call that ran, "
        "with the args that produced its result, or run it with these args"
    )


def _matched_call(step: ToolStep | ForEachStep, walk: _Walk) -> tuple[int, RecordedResult] | None:
    """Return the recorded call this step froze, with its position, or None.

    Agreement is structural (_agrees), not per-arg — a deciding difference is
    often nested under an arg that itself carries a placeholder. Among calls
    that agree, the LAST wins; a step agreeing with none is unmatched, and an
    already-consumed call is never offered again.
    """
    agreeing = [
        (index, call)
        for index, call in enumerate(walk.results or ())
        if call.tool_name == step.tool
        and call.subagent == walk.scope
        and index not in walk.consumed
        and all(
            key in call.args and _agrees(value, call.args[key]) for key, value in step.args.items()
        )
    ]
    return agreeing[-1] if agreeing else None


def _agrees(step_value: object, recorded_value: object) -> bool:
    """Whether a step's authored value could be the recorded call's value.

    An $ask/$time slot or a bare placeholder token agrees with anything
    (unknowable until replay); an embedded token agrees with any string. A
    mapping agrees if every step-written key is present and agrees (extra
    recorded keys are fine); a list agrees elementwise at equal length.
    """
    if is_ask_slot(step_value) or is_time_slot(step_value):
        return True
    if isinstance(step_value, str):
        if PLACEHOLDER_TOKEN.fullmatch(step_value):
            return True
        if PLACEHOLDER_TOKEN.search(step_value):
            return isinstance(recorded_value, str)
        return step_value == recorded_value
    if isinstance(step_value, Mapping):
        return isinstance(recorded_value, Mapping) and all(
            key in recorded_value and _agrees(item, recorded_value[key])
            for key, item in step_value.items()
        )
    if isinstance(step_value, list):
        return (
            isinstance(recorded_value, list)
            and len(step_value) == len(recorded_value)
            # strict= can never fire: the length check above short-circuits first,
            # so no mutation of it is observable (same construct as trigger_dispatch_tasks).
            and all(
                _agrees(item, other)
                for item, other in zip(step_value, recorded_value, strict=True)  # pragma: no mutate
            )
        )
    return step_value == recorded_value


def _result_refusal(tool_name: str, call: RecordedResult) -> str | None:
    """Why the call this step froze is not worth freezing, or None.

    The error envelope is tested first: a tool that reports its own failure
    often does so with an empty list beside it, and "returned no items" would
    name the symptom while the message says the cause.
    """
    if is_error_envelope(call.result):
        return (
            f"{tool_name} failed in this run ({_envelope_error(call.result)}); a playbook "
            "freezes calls that succeeded. Fix the call and run it again, or drop the step"
        )
    # Not a list length: a write tool answers with the record it just made, and
    # that record's own empty attributes are not the call returning nothing.
    # See carries_no_data.
    if carries_no_data(call.result):
        return (
            f"{tool_name} returned no items in this run (args: {_rendered_args(call.args)}); "
            "freeze a call that produced data. Widen the args or decline the playbook"
        )
    return None


def _envelope_error(result: object) -> str:
    """Return what a failed tool said about its own failure, as one phrase."""
    if isinstance(result, dict):
        reported = result.get("error") or result.get("message")
        if reported:
            return str(reported)[:_ARGS_IN_MESSAGE_MAX_CHARS]
    return "the call reported success: false"


def _rendered_args(args: Mapping[str, Any]) -> str:
    # ensure_ascii=False and ensure_ascii=None are byte-identical to json (it
    # only tests truthiness), so that mutation is provably equivalent and exempt.
    rendered = json.dumps(dict(args), default=str, ensure_ascii=False)  # pragma: no mutate
    if len(rendered) <= _ARGS_IN_MESSAGE_MAX_CHARS:
        return rendered
    return rendered[:_ARGS_IN_MESSAGE_MAX_CHARS] + "..."


#: What ``_check_step_reference`` hands back when there was nothing to resolve
#: against, or the reference did not resolve; distinct from a resolved ``None``.
_UNRESOLVED = object()
#: The elements of an ``$ask`` source: text values the model picks at replay.
ASK_PICK = object()


@dataclass(frozen=True, slots=True)
class _Elements:
    """The elements a for_each will run over, as the authoring run saw them."""

    items: tuple[object, ...]


def _check_step_reference(token: str, path: str, where: str, walk: _Walk) -> object:
    """Resolve one $steps reference against what that step returned in this run.

    Through the evaluator's own resolver, so an accepted reference is one the
    replay can actually resolve. .file is exempt (offloaded only at replay).
    Returns the resolved value, or _UNRESOLVED.
    """
    step_id, _, rest = path.partition(".")
    if rest == STEP_FILE_FIELD:
        return _UNRESOLVED
    result = walk.step_results.get(step_id)
    if result is None:
        # The step is declared but its own call was never matched (a handoff
        # child, or a tool this run did not call — both already reported).
        return _UNRESOLVED
    try:
        return resolve_step(token, path, walk.step_results)
    except PlaceholderError as error:
        walk.issues.append(
            PlaybookIssue(where=where, problem=error.message + _shape_hint(result.value))
        )
        return _UNRESOLVED


def _shape_hint(value: object) -> str:
    """Return the keys the result does have, so the author can address one of them."""
    if not isinstance(value, Mapping):
        return ""
    keys = sorted(str(key) for key in value)
    listed = ", ".join(keys[:_MAX_LISTED_KEYS])
    if len(keys) > _MAX_LISTED_KEYS:
        listed += ", ..."
    return f"; its result has keys: {listed}"


def _check_required_args(
    step: ToolStep | ForEachStep, tool_name: str, path: str, space: ToolSpace, walk: _Walk
) -> None:
    """Flag a missing required arg: a call that fails at replay before it starts.

    Nothing else catches it: the per-arg checks walk the args the step HAS, and
    a run-result match agrees with an empty mapping trivially.
    """
    tool = space.tools[tool_name]
    for name in sorted(_required_args(tool) - set(step.args)):
        walk.issues.append(
            PlaybookIssue(
                where=f"{path}.args",
                problem=f"{tool_name} requires {name!r} and this step does not set it; "
                f"it takes: {', '.join(sorted(tool.args))}",
            )
        )


def _required_args(tool: BaseTool) -> set[str]:
    """Return the arg names a tool cannot be called without, from its own call schema.

    tool.args is only the property map; the required list lives one
    level up, on the schema that tool_call_schema renders. langchain hands
    that back as a v2 model for decorated tools, a v1 model for legacy ones and
    a raw JSON document for MCP tools; all three spell required the same way.
    """
    schema = tool.tool_call_schema
    if isinstance(schema, dict):
        rendered: Mapping[str, Any] = schema
    elif issubclass(schema, BaseModel):
        rendered = schema.model_json_schema()
    else:
        rendered = schema.schema()
    return set(rendered.get("required") or [])


def _check_ask_slot(slot: Mapping[str, Any], where: str, walk: _Walk) -> None:
    """One inline ask slot, checked as the model wrote it.

    The whole slot vocabulary is two keys, so the message names both rather than
    relaying pydantic: the author reading this back has to know what a valid
    slot looks like, not which field raised.
    """
    try:
        AskSlot.model_validate(slot)
    except ValidationError:
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem="an $ask slot takes only '$ask' (what to write) and an optional "
                f"max_tokens 1..8192; got {sorted(slot)}",
            )
        )


def _check_placeholder(
    match: re.Match[str],
    where: str,
    walk: _Walk,
    *,
    in_for_each: bool,
    sample: object = NO_ITEM,
) -> None:
    """Check one placeholder: $item against the loop it is in, $steps against the steps declared before it."""
    if match.group("root") == "item":
        _check_item_placeholder(match, where, walk, in_for_each=in_for_each, sample=sample)
    else:
        _check_step_placeholder(match, where, walk)


def _check_item_placeholder(
    match: re.Match[str], where: str, walk: _Walk, *, in_for_each: bool, sample: object
) -> None:
    token = match.group(0)
    path = match.group("path").removeprefix(".")
    if not in_for_each:
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{token} addresses the element of a for_each, and this step is not one",
            )
        )
    elif sample is ASK_PICK:
        # Seen live (D3): ``$item.title`` over an $ask pick. A pick is the text
        # the model copied from the results, so there is no field under it.
        if path:
            walk.issues.append(
                PlaybookIssue(
                    where=where,
                    problem=(
                        f"{token} reads a field of an $ask pick, but each pick is one text "
                        "value; write $item on its own, or make for_each a $steps list and "
                        "read the field off its elements"
                    ),
                )
            )
    elif isinstance(sample, _Elements):
        # Checked against every element the loop can reach: a field the first
        # element has but a later one lacks would stop the loop after the
        # earlier calls already ran.
        for index, element in enumerate(sample.items):
            try:
                resolve_item(token, path, element)
            except PlaceholderError as error:
                at = f" (element {index})" if index else ""
                walk.issues.append(
                    PlaybookIssue(where=where, problem=error.message + at + _shape_hint(element))
                )
                return


def _check_step_placeholder(match: re.Match[str], where: str, walk: _Walk) -> object:
    """Check a $steps reference names a declared step, not a handoff.

    When the run is in hand, also resolves the value that step returned, or
    _UNRESOLVED. Other roots are never seen here — the tokenizer only matches
    known roots.
    """
    token = match.group(0)
    root = match.group("root")
    path = match.group("path").lstrip(".")
    name = path.partition(".")[0]
    if root != "steps":
        return _UNRESOLVED
    if name not in walk.declared_steps:
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{token} points at a step that no earlier node declares",
            )
        )
        return _UNRESOLVED
    if name in walk.handoff_ids:
        child = path.split(".")[1] if "." in path else "<child>"
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=(
                    f"{token} addresses the handoff {name!r}, which records no result of "
                    f"its own; address the call inside it by its own id, $steps.{child}..."
                ),
            )
        )
        return _UNRESOLVED
    if walk.results is None:
        return _UNRESOLVED
    return _check_step_reference(token, path, where, walk)


def _check_for_each_source(step: ForEachStep, path: str, walk: _Walk) -> object:
    """Return one element of the for_each list this run can name, or NO_ITEM.

    Checked against a real element from the run's results so $item.<field> is
    validated here instead of on the first replay iteration. An $ask source
    has nothing to check; a $steps source is also checked for shape — a
    count or title is not a list.
    """
    source = step.for_each
    if isinstance(source, AskSlot):
        return ASK_PICK
    where = f"{path}.for_each"
    match = PLACEHOLDER_TOKEN.fullmatch(source)
    if match is None:  # the model validator already refused anything else
        return NO_ITEM
    if match.group("root") == "item":
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=(
                    f"{source} addresses the element of a for_each, and the list itself "
                    "cannot be one of its own elements"
                ),
            )
        )
        return NO_ITEM
    resolved = _check_step_placeholder(match, where, walk)
    if resolved is _UNRESOLVED:
        return NO_ITEM
    if isinstance(resolved, list):
        return _Elements(tuple(resolved[: step.max_items])) if resolved else NO_ITEM
    result = walk.step_results[match.group("path").removeprefix(".").partition(".")[0]]
    walk.issues.append(
        PlaybookIssue(
            where=where,
            problem=(
                f"{source} resolved to {type(resolved).__name__}, and for_each needs a list "
                "to repeat over" + _shape_hint(result.value)
            ),
        )
    )
    return NO_ITEM


_TIME_ROOTS = frozenset({"now", "today"})


def _time_slot_hint(placeholder: str, layout: str) -> str:
    return json.dumps({TIME_KEY: placeholder, "format": layout})


def _check_time_slot(
    value: Mapping[str, Any], key: str, where: str, recorded: RecordedResult | None, walk: _Walk
) -> None:
    """Check a $time slot is well-formed and its layout is the one the tool took."""
    try:
        slot = TimeSlot.model_validate(value)
    except ValidationError as error:
        walk.issues.append(PlaybookIssue(where=where, problem=_first_validation_message(error)))
        return
    layout = detect_layout(recorded.args.get(key)) if recorded is not None else None
    if layout is not None and layout != slot.format:
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=(
                    f"{key!r} was {recorded.args.get(key)!r} in this run, whose layout is "
                    f"{layout!r}, not {slot.format!r}; write "
                    f"{_time_slot_hint(slot.placeholder, layout)}"
                ),
            )
        )


def _check_time_layout(
    value: object,
    tokens: Sequence[re.Match[str]],
    key: str,
    where: str,
    recorded: RecordedResult | None,
    walk: _Walk,
) -> None:
    """Check a time placeholder renders in the tool's layout, or refuse it.

    Prose around a placeholder renders to a sentence no tool parses, and a
    bare placeholder renders to ISO 8601, which isn't every tool's layout.
    The recorded argument is the example layout; a mismatch is refused with
    the exact slot to write instead.
    """
    if not isinstance(value, str):
        return
    if recorded is None:
        return
    example = recorded.args.get(key)
    layout = detect_layout(example)
    if layout is None:
        return
    whole = PLACEHOLDER_TOKEN.fullmatch(value)
    placeholder = whole.group(0) if whole is not None else tokens[0].group(0)
    if whole is not None:
        date_only = whole.group("root") == "today" and whole.group("clock") is None
        if layout == (ISO_DATE_LAYOUT if date_only else ISO_DATETIME_LAYOUT):
            return
        problem = (
            f"{key!r} was {example!r} in this run, whose layout is {layout!r}; {value} "
            f"renders as ISO 8601, so write {_time_slot_hint(placeholder, layout)}"
        )
    else:
        problem = (
            f"{key!r} was {example!r} in this run; {value!r} renders its placeholder as "
            f"ISO 8601 inside that text, which is not this layout. Write the whole value as "
            f"{_time_slot_hint(placeholder, layout)}, with the clock inside the placeholder"
        )
    walk.issues.append(PlaybookIssue(where=where, problem=problem))


def _first_validation_message(error: ValidationError) -> str:
    return error.errors()[0]["msg"].removeprefix("Value error, ")


def _check_value_type(
    value: object, arg_schema: object, where: str, issues: list[PlaybookIssue]
) -> None:
    if not isinstance(arg_schema, dict):
        return
    accepted = _accepted_types(arg_schema)
    if not accepted:
        return
    numeric_only = accepted in ((int,), (int, float))
    if isinstance(value, accepted) and not (numeric_only and isinstance(value, bool)):
        return
    issues.append(
        PlaybookIssue(
            where=where,
            problem=f"expected {_describe(arg_schema)}, got {type(value).__name__}",
        )
    )


def _accepted_types(arg_schema: dict[str, Any]) -> tuple[type, ...]:
    declared = arg_schema.get("type")
    if isinstance(declared, str):
        return _JSON_TYPE_TO_PYTHON.get(declared, ())
    variants = arg_schema.get("anyOf") or arg_schema.get("oneOf") or []
    accepted: list[type] = []
    for variant in variants:
        if isinstance(variant, dict):
            accepted.extend(_accepted_types(variant))
    return tuple(accepted)


def _describe(arg_schema: dict[str, Any]) -> str:
    declared = arg_schema.get("type")
    if isinstance(declared, str):
        return declared
    variants = arg_schema.get("anyOf") or arg_schema.get("oneOf") or []
    names = [v["type"] for v in variants if isinstance(v, dict) and isinstance(v.get("type"), str)]
    return " or ".join(names) if names else "another type"
