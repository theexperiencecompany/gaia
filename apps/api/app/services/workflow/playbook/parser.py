"""Check a playbook against the live tool registry, and render it for reading.

``validate_playbook`` asks the registry whether an authored document could
actually run: the tools exist, their args are real, and every reference points
at something the document already declared. Its messages are read back by the
authoring agent, so each one names the offending step and says what would be
valid rather than reporting "invalid".

``dump_playbook`` renders a body as YAML. That rendering is for humans and for
the agent reading its own playbook back; the structured body is the only stored
form, so nothing ever parses the YAML again.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
from typing import Any

from pydantic import BaseModel, Field
import yaml

from app.agents.core.subagents.call_record import ARG_TRUNCATION_MARKER
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.models.playbook_models import PlaybookAsk, PlaybookBody, PlaybookStep
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
    if body.ask:
        document["ask"] = {name: ask.model_dump() for name, ask in body.ask.items()}
    document["synthesize"] = body.synthesize
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


async def validate_playbook(body: PlaybookBody, user_id: str) -> PlaybookValidation:
    """Check a parsed playbook against the tools it would actually reach.

    Three classes of problem, all fatal for a replay: a tool that does not
    exist, an arg the tool does not take (or takes with another type), and a
    reference to a step or ask the document never declares before that point.

    ``user_id`` is required because "does this tool exist" has no user-independent
    answer: a handoff's children run in that subagent's space, and an MCP
    integration's tools live on that user's own client.
    """
    registry = await get_tool_registry()
    walk = _Walk(
        asks=body.ask,
        all_step_ids=_step_ids(body.steps),
        user_id=user_id,
        registry=registry,
    )
    await _check_steps(
        body.steps,
        "steps",
        ToolSpace(tools=registry.get_tool_dict(), runtime=None, subagent_id=None),
        walk,
    )

    for name, ask in body.ask.items():
        for step_id in ask.uses:
            if step_id not in walk.declared_steps:
                walk.issues.append(
                    PlaybookIssue(
                        where=f"ask.{name}.uses",
                        problem=f"no step is declared with id {step_id!r}",
                    )
                )

    return PlaybookValidation(valid=not walk.issues, issues=walk.issues)


@dataclass
class _Walk:
    """What one pass over the document accumulates, in document order."""

    asks: Mapping[str, PlaybookAsk]
    all_step_ids: set[str]
    user_id: str
    registry: ToolRegistry
    declared_steps: set[str] = field(default_factory=set)
    issues: list[PlaybookIssue] = field(default_factory=list)
    #: Set at the first step that addresses any ``$ask``: the runner fills EVERY
    #: ask there, in one model call, from the steps that have run by then.
    asks_filled_at: str | None = None


def _step_ids(steps: Sequence[PlaybookStep]) -> set[str]:
    ids: set[str] = set()
    for step in steps:
        if step.id:
            ids.add(step.id)
        ids |= _step_ids(step.steps)
    return ids


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

    # The evaluator's own scanner, so a placeholder embedded in text
    # ("Email $steps.mail.to") is checked exactly as a whole-value one is.
    tokens = list(placeholder_tokens(step.args))
    if walk.asks_filled_at is None and any(token.group("root") == "ask" for token in tokens):
        walk.asks_filled_at = step.id or path
        _check_asks_fillable(walk)

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
        arg_tokens = list(placeholder_tokens(value))
        for token in arg_tokens:
            _check_placeholder(token, where, walk)
        if not arg_tokens:
            _check_value_type(value, arg_schema, where, walk.issues)


def _check_asks_fillable(walk: _Walk) -> None:
    """Every ask reads only steps that ran before the asks are filled.

    The runner narrates once, at the first step addressing any ``$ask``, and the
    narration sees only the steps completed by then. An ask whose ``uses`` names
    a later step would be written from nothing, silently. An id no step declares
    at all is reported after the walk, not here.
    """
    for name, ask in walk.asks.items():
        for step_id in ask.uses:
            if step_id in walk.declared_steps or step_id not in walk.all_step_ids:
                continue
            walk.issues.append(
                PlaybookIssue(
                    where=f"ask.{name}.uses",
                    problem=f"ask {name!r} reads step {step_id!r}, but the asks are filled at "
                    f"step {walk.asks_filled_at!r} (the first to address $ask), before "
                    f"{step_id!r} runs; move {step_id!r} ahead of {walk.asks_filled_at!r} "
                    "or drop it from uses",
                )
            )


def _check_placeholder(match: re.Match[str], where: str, walk: _Walk) -> None:
    # The tokenizer only matches known roots; any other ``$word`` is literal text.
    token = match.group(0)
    root = match.group("root")
    name = match.group("path").lstrip(".").partition(".")[0]
    if root == "steps" and name not in walk.declared_steps:
        walk.issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{token} points at a step that no earlier node declares",
            )
        )
    elif root == "ask" and name not in walk.asks:
        walk.issues.append(
            PlaybookIssue(
                where=where, problem=f"{token} points at an ask the playbook never declares"
            )
        )


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
