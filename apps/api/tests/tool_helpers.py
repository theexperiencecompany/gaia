"""Helpers for calling @tool functions directly in tests."""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import TypeAdapter

R = TypeVar("R")


def tool_coroutine(tool: BaseTool, returns: type[R]) -> Callable[..., Awaitable[R]]:
    """Return the async function behind an @tool, its result checked against returns (what @tool erased)."""
    assert isinstance(tool, StructuredTool) and tool.coroutine is not None
    coroutine = tool.coroutine
    adapter = TypeAdapter(returns)

    async def call(*args: object, **kwargs: object) -> R:
        result = await coroutine(*args, **kwargs)
        # Checked, not replaced: a tool's caller sees its very object, extra keys included.
        adapter.validate_python(result)
        return result

    return call
