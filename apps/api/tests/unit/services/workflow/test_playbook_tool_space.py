"""The one answer to "may this playbook step run", shared by the validator and the replay runner.

Both read it, so a playbook the validator accepts is one the runner will run,
and a tool the registry does not hold is refused the same way at write time
and at replay.
"""

from unittest.mock import MagicMock

from langchain_core.tools import BaseTool
import pytest

from app.services.workflow.playbook.tool_space import ToolSpace, tool_space_denial

REGISTRY_TOOL = "list_events"


def _tool(name: str) -> BaseTool:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


@pytest.mark.unit
class TestToolSpaceDenial:
    def test_a_tool_in_the_registry_may_run(self) -> None:
        space = ToolSpace(tools={REGISTRY_TOOL: _tool(REGISTRY_TOOL)})

        assert tool_space_denial(REGISTRY_TOOL, space) is None

    def test_a_tool_missing_from_the_registry_does_not_exist(self) -> None:
        space = ToolSpace(tools={REGISTRY_TOOL: _tool(REGISTRY_TOOL)})

        assert tool_space_denial("send_owl", space) == "no tool named 'send_owl' exists"
