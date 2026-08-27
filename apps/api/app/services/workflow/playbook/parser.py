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

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import yaml

from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.models.playbook_models import PlaybookBody, PlaybookStep
from app.services.workflow.playbook.tool_space import resolve_subagent_tools

#: The placeholder namespaces a playbook may address. Everything else is a typo:
#: placeholders are resolved by code, so an unrecognised one would be handed to a
#: tool as the literal ``$whatever`` string.
PLACEHOLDER_ROOTS: frozenset[str] = frozenset(
    {"now", "today", "user", "trigger", "steps", "last_run", "ask"}
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
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


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
    tools = registry.get_tool_dict()

    issues: list[PlaybookIssue] = []
    declared_steps: set[str] = set()
    await _check_steps(
        body.steps, "steps", tools, set(body.ask), declared_steps, issues, user_id, registry
    )

    for name, ask in body.ask.items():
        for step_id in ask.uses:
            if step_id not in declared_steps:
                issues.append(
                    PlaybookIssue(
                        where=f"ask.{name}.uses",
                        problem=f"no step is declared with id {step_id!r}",
                    )
                )

    return PlaybookValidation(valid=not issues, issues=issues)


async def _check_steps(
    steps: Sequence[PlaybookStep],
    path: str,
    tools: Mapping[str, BaseTool],
    ask_names: set[str],
    declared_steps: set[str],
    issues: list[PlaybookIssue],
    user_id: str,
    registry: ToolRegistry,
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
            _check_tool_step(step, here, tools, ask_names, declared_steps, issues)
        else:
            space = await resolve_subagent_tools(step.handoff or "", user_id, registry)
            if space is None:
                issues.append(
                    PlaybookIssue(
                        where=here,
                        problem=f"no subagent named {step.handoff!r} exists to hand off to",
                    )
                )
            else:
                await _check_steps(
                    step.steps,
                    f"{here}.steps",
                    space.tools,
                    ask_names,
                    declared_steps,
                    issues,
                    user_id,
                    registry,
                )
        if step.id:
            declared_steps.add(step.id)


def _check_tool_step(
    step: PlaybookStep,
    path: str,
    tools: Mapping[str, BaseTool],
    ask_names: set[str],
    declared_steps: set[str],
    issues: list[PlaybookIssue],
) -> None:
    tool = tools.get(step.tool) if step.tool else None
    if tool is None:
        issues.append(PlaybookIssue(where=path, problem=f"no tool named {step.tool!r} exists"))
        return

    schema: dict[str, Any] = tool.args
    for key, value in step.args.items():
        where = f"{path}.args.{key}"
        arg_schema = schema.get(key)
        if arg_schema is None:
            issues.append(
                PlaybookIssue(
                    where=where,
                    problem=f"{step.tool} takes no arg {key!r}; it takes: "
                    f"{', '.join(sorted(schema)) or 'nothing'}",
                )
            )
            continue
        for token in _placeholders(value):
            _check_placeholder(token, where, ask_names, declared_steps, issues)
        if not _has_placeholder(value):
            _check_value_type(value, arg_schema, where, issues)


def _check_placeholder(
    token: str,
    where: str,
    ask_names: set[str],
    declared_steps: set[str],
    issues: list[PlaybookIssue],
) -> None:
    root, rest = _split_placeholder(token)
    if root not in PLACEHOLDER_ROOTS:
        issues.append(
            PlaybookIssue(
                where=where,
                problem=f"unknown placeholder {token!r}; the namespaces are "
                f"{', '.join(sorted(PLACEHOLDER_ROOTS))}",
            )
        )
        return
    name = rest.partition(".")[0]
    if root == "steps" and name not in declared_steps:
        issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{token} points at a step that no earlier node declares",
            )
        )
    elif root == "ask" and name not in ask_names:
        issues.append(
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


def _placeholders(value: object) -> Iterator[str]:
    """Every ``$...`` token in a value, however deeply nested."""
    if isinstance(value, str):
        if value.startswith("$"):
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _placeholders(item)
    elif isinstance(value, list):
        for item in value:
            yield from _placeholders(item)


def _has_placeholder(value: object) -> bool:
    return any(True for _ in _placeholders(value))


def _split_placeholder(token: str) -> tuple[str, str]:
    """``$steps.draft.file`` becomes ``("steps", "draft.file")``; ``$now + 1d``
    becomes ``("now", "")`` because the offset is resolved, not referenced."""
    head = token[1:].split(maxsplit=1)[0] if token[1:].strip() else ""
    root, _, rest = head.partition(".")
    return root, rest
