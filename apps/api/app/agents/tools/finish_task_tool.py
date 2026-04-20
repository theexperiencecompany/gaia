"""Finish task tool for subagent completion."""

from langchain_core.tools import tool


@tool(description="Finish the task and return the final result to the parent.")
async def finish_task(result: str) -> str:
    return result
