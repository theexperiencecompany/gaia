"""Replay a corpus attempt through the pick flow: build the playbook, then validate it.

Offline: the registry is built from the record itself, one tool per recorded
tool name, taking exactly the args it was recorded with and requiring none.
That is the contract the pick flow stands on (a recorded call already passed
its tool's schema when it ran), so what this proves is the pick, build and
validation logic, not tool schema drift since the run.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

from langchain_core.tools import BaseTool, StructuredTool

from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.playbook_tools import UNPICKABLE_TOOLS
from app.constants.execute import EXECUTE_TOOL_NAME
from app.models.playbook_models import ForEachStep, PlaybookRefusal, ToolStep
from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook import parser
from app.services.workflow.playbook.parser import PlaybookIssue, validate_playbook
from app.services.workflow.playbook.record import (
    PlaybookPick,
    RecordEntry,
    build_playbook,
    record_entries,
)


@dataclass
class Outcome:
    """What the pick flow did with one attempt."""

    issues: list[PlaybookIssue] = field(default_factory=list)

    @property
    def refusals(self) -> list[PlaybookRefusal]:
        return sorted({issue.kind for issue in self.issues}, key=lambda kind: kind.value)


def entries(record: Sequence[RecordedCall], record_len: int) -> list[RecordEntry]:
    """The record an attempt picked from, with the ids read_run_record shows."""
    return record_entries(record[:record_len], UNPICKABLE_TOOLS)


async def replay(
    description: str,
    picks: Sequence[PlaybookPick],
    result_brief: str,
    record: Sequence[RecordEntry],
    replaces: Sequence[ToolStep | ForEachStep] = (),
) -> Outcome:
    """Build and validate one attempt's picks against a registry made from its record."""
    built = build_playbook(description, picks, result_brief, record, replaces=replaces)
    if built.body is None:
        return Outcome(issues=built.issues)
    registry = _Registry(_recorded_tools(record))
    with patch.object(parser, "get_tool_registry", AsyncMock(return_value=registry)):
        validation = await validate_playbook(built.body, built.sources)
    return Outcome(issues=validation.issues)


@dataclass(frozen=True, slots=True)
class _Registry:
    tools: dict[str, BaseTool]

    def get_tool_dict(self) -> dict[str, BaseTool]:
        return self.tools


def _recorded_tools(record: Sequence[RecordEntry]) -> dict[str, BaseTool]:
    args: defaultdict[str, set[str]] = defaultdict(set)
    for entry in record:
        args[entry.call.tool_name] |= set(entry.call.args)
    tools: dict[str, BaseTool] = {name: _tool(name, names) for name, names in args.items()}
    tools[EXECUTE_TOOL_NAME] = execute
    return tools


def _tool(name: str, arg_names: set[str]) -> BaseTool:
    async def run(**_: object) -> str:
        raise RuntimeError(f"{name} is a corpus stand-in and never runs")

    schema = {
        "type": "object",
        "properties": {arg: {} for arg in sorted(arg_names)},
        "required": [],
    }
    return StructuredTool.from_function(
        coroutine=run, name=name, description=f"{name}, as recorded.", args_schema=schema
    )
