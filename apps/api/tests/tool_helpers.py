"""Helpers for calling @tool functions directly in tests."""

from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, StructuredTool


def tool_coroutine(tool: BaseTool) -> Callable[..., Awaitable[str]]:
    """Return the async function behind an @tool, to call it without the tool's argument schema."""
    assert isinstance(tool, StructuredTool) and tool.coroutine is not None
    return tool.coroutine
