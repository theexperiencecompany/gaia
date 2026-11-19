"""Helpers for calling @tool functions directly in tests."""

from collections.abc import Awaitable, Callable
from typing import TypeVar, overload

from langchain_core.tools import BaseTool, StructuredTool

_R = TypeVar("_R")


@overload
def tool_coroutine(tool: BaseTool) -> Callable[..., Awaitable[str]]: ...
@overload
def tool_coroutine(tool: BaseTool, returns: type[_R]) -> Callable[..., Awaitable[_R]]: ...
def tool_coroutine(tool: BaseTool, returns: type[object] = str) -> Callable[..., Awaitable[object]]:
    """Return the async function behind an @tool, to call it without the tool's argument schema.

    returns names what it resolves to when that is not the usual str (a dict-shaped result).
    """
    assert isinstance(tool, StructuredTool) and tool.coroutine is not None
    return tool.coroutine
