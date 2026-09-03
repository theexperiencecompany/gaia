"""Check a playbook against the live tool registry, and render it for reading.

``validate_playbook`` asks the registry whether an authored document could
actually run: the tools exist, their args are real, and every reference points
at something the document already declared. Its messages are read back by the
authoring agent, so each one names the offending step and says what would be
valid rather than reporting "invalid".

Given the authoring run's own results it asks a second, sharper question: did
these calls actually happen, and did they return what the document claims to
read? A playbook freezes calls that ran, so the run writing it holds every
answer — ``pb_c7d357db77dd`` froze ``$steps.fetch_msgs.threadId`` on a tool that
returns no ``threadId`` and broke on its first replay, with the real result
sitting in the same conversation.

``dump_playbook`` renders a body as YAML. That rendering is for humans and for
the agent reading its own playbook back; the structured body is the only stored
form, so nothing ever parses the YAML again.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError
import yaml

from app.agents.core.subagents.call_record import ARG_TRUNCATION_MARKER, is_error_envelope
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.models.playbook_models import (
    AskSlot,
    PlaybookBody,
    PlaybookStep,
    has_ask_slots,
    walk_ask_slots,
)
from app.models.workflow_execution_models import largest_list_len
from app.services.workflow.playbook.evaluator import (
    STEP_FILE_FIELD,
    PlaceholderError,
    StepResult,
    resolve_step,
)
from app.services.workflow.playbook.placeholders import placeholder_tokens
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

    ``result`` is parsed the way the replay parses a result (JSON when it is
    JSON, the raw text otherwise), so a check here reads exactly the value a
    ``$steps`` placeholder would resolve against at replay.
    """

    tool_name: str
    args: Mapping[str, Any]
    result: object


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
        "steps": [_dump_step(step) for step in body.steps],
    }
    # Args are dumped as authored, so an inline ask slot renders as a nested
    # ``$ask:`` mapping right where its value belongs — which is exactly how the
    # agent should read it back when it revises the playbook.
    document["result_brief"] = body.result_brief
    # sort_keys=False and sort_keys=None are byte-identical to PyYAML (it only
    # tests truthiness), so that mutation is provably equivalent and exempt.
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)  # pragma: no mutate


def _dump_step(step: PlaybookStep) -> dict[str, Any]:
    node: dict[str, Any] = {}
    if step.id:
        node["id"] = step.id
    if step.tool:
        node["tool"] = step.tool
    if step.args:
        node["args"] = step.args
    if step.handoff:
        node["handoff"] = step.handoff
    if step.steps:
        node["steps"] = [_dump_step(child) for child in step.steps]
    return node


async def validate_playbook(
    body: PlaybookBody, user_id: str, results: RunResults | None = None
) -> PlaybookValidation:
    """Check a parsed playbook against the tools it would actually reach.

    Three classes of problem, all fatal for a replay: a tool that does not
    exist, an arg the tool does not take (or takes with another type), and a
    reference to a step the document never declares before that point.

    ``user_id`` is required because "does this tool exist" has no user-independent
    answer: a handoff's children run in that subagent's space, and an MCP
    integration's tools live on that user's own client.

    ``results`` are the calls the run writing this playbook actually made. With
    them a fourth class of problem is answerable here rather than on the first
    replay: a step naming a tool that never ran, a step freezing a call that
    came back empty or errored, and a ``$steps`` reference into a shape the
    tool does not return. Without them nothing changes — the dev executor route
    and any caller with no run behind it get exactly the checks above.
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
    issues: list[PlaybookIssue] = field(default_factory=list)
    #: The authoring run's calls, or ``None`` when there is no run to check
    #: against. ``None`` and an empty run are different: an empty run means
    #: every tool step froze a call that never happened.
    results: RunResults | None = None
    #: What each declared step returned in that run, filled as the walk passes
    #: the step. A ``$steps`` reference is checked against this, so it can only
    #: ever read a step that ran before it — the same rule the replay enforces.
    step_results: dict[str, StepResult] = field(default_factory=dict)


async def _check_steps(
    steps: Sequence[PlaybookStep], path: str, space: ToolSpace, walk: _Walk
) -> None:
    """Walk the steps in document order, so a reference can only resolve
    backwards: ``declared_steps`` holds exactly what ran before this node.

    Descending into a handoff switches tool space, exactly as the replay does.
    Checking a subagent's children against the executor's registry refuses every
    integration whose tools are fetched per user.
    """
    for index, step in enumerate(steps):
        here = f"{path}[{index}]"
        if step.tool:
            _check_tool_step(step, here, space, walk)
        else:
            handoff = step.handoff
            if handoff is None:
                # exactly_one_shape forbids a step with neither shape; narrowed
                # here because mypy cannot see the validator.
                continue
            subagent = await resolve_subagent_tools(handoff, walk.user_id, walk.registry)
            if subagent is None:
                walk.issues.append(
                    PlaybookIssue(
                        where=here,
                        problem=f"no subagent named {step.handoff!r} exists to hand off to",
                    )
                )
            else:
                await _check_steps(step.steps, f"{here}.steps", handoff_tool_space(subagent), walk)
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


def _check_tool_step(step: PlaybookStep, path: str, space: ToolSpace, walk: _Walk) -> None:
    if step.tool is None:
        # exactly_one_shape forbids a tool-less step reaching here; this guard
        # narrows the type where mypy cannot see the validator.
        return
    tool_name = step.tool
    denial = tool_space_denial(tool_name, space)
    if denial is not None:
        walk.issues.append(PlaybookIssue(where=path, problem=denial))
        return

    if walk.results is not None:
        _check_recorded_call(step, tool_name, path, space, walk)

    schema: dict[str, Any] = space.tools[tool_name].args
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
        arg_tokens = list(placeholder_tokens(value))
        for token in arg_tokens:
            _check_placeholder(token, where, walk)
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
    step: PlaybookStep, tool_name: str, path: str, space: ToolSpace, walk: _Walk
) -> None:
    """Check one tool step against the call it froze in the run writing it.

    Matching the step back to a recorded call is also what makes the ``$steps``
    references checkable: the matched result is what later steps read from.

    A handoff's children are exempt from "did not run". The record a handoff
    appends (``call_record.py``) carries the subagent's tool names and args but
    NOT their outputs, so this run's results hold nothing for them and their
    absence is evidence of nothing.
    """
    call = _matched_call(step, walk)
    if call is None:
        if space.subagent_id is None:
            walk.issues.append(
                PlaybookIssue(
                    where=path,
                    problem=f"{tool_name} did not run in this run; a playbook freezes calls "
                    "that ran and produced their result — run it, or drop the step",
                )
            )
        return
    if step.id:
        walk.step_results[step.id] = StepResult(value=call.result)
    refusal = _result_refusal(tool_name, call)
    if refusal is not None:
        walk.issues.append(PlaybookIssue(where=path, problem=refusal))


def _matched_call(step: PlaybookStep, walk: _Walk) -> RecordedResult | None:
    """The recorded call this step froze, or ``None`` when the tool never ran.

    A step's literal args are the only evidence of WHICH call it froze: a tool
    called three times with different queries left three results, and checking
    the step against the wrong one reports a shape the author never claimed. An
    arg holding a placeholder or an ``$ask`` slot is a wildcard — the value it
    stands for does not exist until replay, so it cannot disagree with
    anything. The LAST call wins, both among the calls that agree and as the
    fallback when none does: a run that repeats a tool settles on its final
    call, which is the one worth freezing.
    """
    calls = [call for call in (walk.results or ()) if call.tool_name == step.tool]
    if not calls:
        return None
    literals = {
        key: value
        for key, value in step.args.items()
        if not any(True for _ in placeholder_tokens(value)) and not has_ask_slots(value)
    }
    agreeing = [
        call
        for call in calls
        if all(key in call.args and call.args[key] == value for key, value in literals.items())
    ]
    return (agreeing or calls)[-1]


def _result_refusal(tool_name: str, call: RecordedResult) -> str | None:
    """Why the call this step froze is not worth freezing, or ``None``.

    The error envelope is tested first: a tool that reports its own failure
    often does so with an empty list beside it, and "returned no items" would
    name the symptom while the message says the cause.
    """
    if is_error_envelope(call.result):
        return (
            f"{tool_name} failed in this run ({_envelope_error(call.result)}); a playbook "
            "freezes calls that succeeded — fix the call and run it again, or drop the step"
        )
    # None means the result carries no list at all (a single object, a string),
    # which says nothing about emptiness; only a list of length zero does.
    if largest_list_len(call.result) == 0:
        return (
            f"{tool_name} returned no items in this run (args: {_rendered_args(call.args)}); "
            "freeze a call that produced data — widen the args or decline the playbook"
        )
    return None


def _envelope_error(result: object) -> str:
    """What a failed tool said about its own failure, as one phrase."""
    if isinstance(result, dict):
        reported = result.get("error") or result.get("message")
        if reported:
            return str(reported)[:_ARGS_IN_MESSAGE_MAX_CHARS]
    return "the call reported success: false"


def _rendered_args(args: Mapping[str, Any]) -> str:
    rendered = json.dumps(dict(args), default=str, ensure_ascii=False)
    if len(rendered) <= _ARGS_IN_MESSAGE_MAX_CHARS:
        return rendered
    return rendered[:_ARGS_IN_MESSAGE_MAX_CHARS] + "..."


def _check_step_reference(token: str, path: str, where: str, walk: _Walk) -> None:
    """Resolve one ``$steps`` reference against what that step returned in this run.

    Through the evaluator's own resolver, so an accepted reference is one the
    replay can actually resolve rather than one a second path-walker agreed
    with. ``.file`` is exempt: the offloaded file exists only at replay, and the
    authoring run's result has no path to it.
    """
    step_id, _, rest = path.partition(".")
    if rest == STEP_FILE_FIELD:
        return
    result = walk.step_results.get(step_id)
    if result is None:
        # The step is declared but its own call was never matched (a handoff
        # child, or a tool this run did not call — both already reported).
        return
    try:
        resolve_step(token, path, walk.step_results)
    except PlaceholderError as error:
        walk.issues.append(
            PlaybookIssue(where=where, problem=error.message + _shape_hint(result.value))
        )


def _shape_hint(value: object) -> str:
    """The keys the result does have, so the author can address one of them."""
    if not isinstance(value, Mapping):
        return ""
    keys = sorted(str(key) for key in value)
    listed = ", ".join(keys[:_MAX_LISTED_KEYS])
    if len(keys) > _MAX_LISTED_KEYS:
        listed += ", ..."
    return f"; its result has keys: {listed}"


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


def _check_placeholder(match: re.Match[str], where: str, walk: _Walk) -> None:
    # The tokenizer only matches known roots; any other ``$word`` is literal text.
    token = match.group(0)
    root = match.group("root")
    path = match.group("path").lstrip(".")
    name = path.partition(".")[0]
    if root != "steps":
        return
    if name not in walk.declared_steps:
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{token} points at a step that no earlier node declares",
            )
        )
        return
    if walk.results is not None:
        _check_step_reference(token, path, where, walk)


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
