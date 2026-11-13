"""Resolve the tools a playbook step is allowed to name.

Every step runs against the executor's registry. Integration tools (Composio,
MCP, custom MCP) are reached through execute, which resolves them per user
at call time, so the registry is the whole space. The validator and the replay
runner both answer "may this step run" here, so they cannot disagree.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.tools import BaseTool


@dataclass(frozen=True, slots=True)
class ToolSpace:
    """Where a step's tool is looked up: the executor's registry."""

    tools: Mapping[str, BaseTool]


def tool_space_denial(tool_name: str, space: ToolSpace) -> str | None:
    """Why this space may not run tool_name, or None when it may."""
    if tool_name not in space.tools:
        return f"no tool named {tool_name!r} exists"
    return None
