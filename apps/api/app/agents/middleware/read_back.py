"""Read-back verification: confirm a write actually happened by re-reading.

A personal assistant has no test suite. The manufactured oracle for a write
action is an independent re-read of the same resource: after an irreversible or
state-changing tool succeeds, run its paired read-back and append the result to
the tool message, so the model (and the user) see confirmation grounded in the
world rather than trusting the write tool's own success string.

A ``ReadBackContract`` pairs a write tool with a verifier that may call read
tools (held on the middleware, set via ``set_tools``). Contracts are injected, so
the mechanism is toolkit-agnostic and unit-testable without real integrations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# A verifier receives (write_args, write_result_text, tools_by_name) and returns a
# short confirmation/mismatch note to append, or None to add nothing.
Verifier = Callable[[dict[str, Any], str, dict[str, BaseTool]], Awaitable[str | None]]


class ReadBackContract:
    """Pairs a write tool with a read-back verifier."""

    __slots__ = ("verify",)

    def __init__(self, verify: Verifier) -> None:
        self.verify = verify


class ReadBackMiddleware(AgentMiddleware):
    """After a contracted write tool succeeds, re-read to confirm the effect."""

    def __init__(self, contracts: dict[str, ReadBackContract]) -> None:
        super().__init__()
        self._contracts = contracts
        self._tools_by_name: dict[str, BaseTool] = {}

    def set_tools(self, tools: list[BaseTool]) -> None:
        self._tools_by_name = {t.name: t for t in tools}

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)

        tool_call = request.tool_call
        name = tool_call.get("name", "") if isinstance(tool_call, dict) else tool_call.name
        contract = self._contracts.get(name)
        if contract is None:
            return result
        # Only verify a write that actually reported success.
        if not isinstance(result, ToolMessage) or getattr(result, "status", None) == "error":
            return result

        args = tool_call.get("args", {}) if isinstance(tool_call, dict) else tool_call.args
        try:
            note = await contract.verify(args or {}, str(result.content), self._tools_by_name)
        except Exception as e:  # noqa: BLE001 - verification must never break the run
            log.warning(f"{LogTag.AGENT} read-back verify failed for {name}: {e}")
            return result

        if note:
            result.content = f"{result.content}\n\n[Read-back verification] {note}"
            result.additional_kwargs = {
                **getattr(result, "additional_kwargs", {}),
                "read_back_verified": True,
            }
        return result
