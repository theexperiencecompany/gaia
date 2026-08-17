"""Behavior tests for app.agents.tools.finish_task_tool.

The tool is the subagent's terminal handoff: it must echo the result verbatim
and its name must match FINISH_TASK_NAME (the invariant the import-time assert
guards).
"""

from app.agents.tools.finish_task_tool import finish_task
from app.constants.general import FINISH_TASK_NAME


class TestFinishTask:
    async def test_name_matches_the_routing_constant(self) -> None:
        assert finish_task.name == FINISH_TASK_NAME

    async def test_result_is_returned_verbatim(self) -> None:
        result = await finish_task.coroutine(result="The full deliverable data.")
        assert result == "The full deliverable data."

    async def test_multi_line_results_are_untouched(self) -> None:
        result = await finish_task.coroutine(result="line 1\nline 2\n- item")
        assert result == "line 1\nline 2\n- item"

    async def test_empty_result_is_returned_as_is(self) -> None:
        assert await finish_task.coroutine(result="") == ""
