"""Tool-loop guardrail middleware.

Repeats: a call identical to the ones the model issued on its previous turns of
the current delegation is warned on the second turn and not run from the third.
Failures: a failing call gets an in-band note once this exact call has failed
LOOP_GUARD_WARN_IDENTICAL times in a row, or its tool LOOP_GUARD_WARN_SAME_TOOL
times. Both are read off the current delegation's messages, so a new delegation
or user turn on the same thread starts clean.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import hashlib
import json
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, AnyMessage, ToolCall, ToolMessage
from langgraph.types import Command

from app.agents.middleware.completion import current_delegation
from app.constants.agents import TOOL_RESULT_NOTE_SEPARATOR
from app.constants.llm import (
    LOOP_GUARD_STOP_REPEAT,
    LOOP_GUARD_STOPPED_KEY,
    LOOP_GUARD_WARN_IDENTICAL,
    LOOP_GUARD_WARN_REPEAT,
    LOOP_GUARD_WARN_SAME_TOOL,
)
from app.constants.log_tags import LogTag
from app.override.langgraph_bigtool.utils import State
from app.services.hil.utils import raw_tool_call
from shared.py.wide_events import log

_CallKey = tuple[str, str]


class LoopGuardMiddleware(AgentMiddleware):
    """Refuse a model's repeated identical call; nudge a tool that keeps failing."""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[str]]],
    ) -> ToolMessage | Command[str]:
        call = raw_tool_call(request)
        tool_name, tool_call_id = call.name, call.id
        call_key = (tool_name, self._args_key(call.args))
        delegation = self._delegation(request)

        repeat = self._repeat_streak(delegation, call_key)
        if repeat >= LOOP_GUARD_STOP_REPEAT:
            log.warning(
                f"{LogTag.AGENT} Loop guard refused a repeated call — not executed",
                tool_name=tool_name,
                repeat=repeat,
            )
            return ToolMessage(
                content=(
                    f"[Loop guard] This `{tool_name}` call was not run: it repeats your last "
                    f"{repeat - 1} calls with identical arguments, and its result will not "
                    "change. Your next step must be a different action or your final answer."
                ),
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
                additional_kwargs={LOOP_GUARD_STOPPED_KEY: True},
            )

        result = await handler(request)
        if not isinstance(result, ToolMessage) or getattr(result, "status", None) != "error":
            # A successful call that repeats identical arguments is still a loop —
            # warn in-band so the model reuses the earlier result instead of
            # re-issuing the same handoff/search.
            if isinstance(result, ToolMessage) and repeat >= LOOP_GUARD_WARN_REPEAT:
                log.warning(
                    f"{LogTag.AGENT} Loop guard repeat-warning appended for tool",
                    tool_name=tool_name,
                    repeat=repeat,
                )
                self._append_note(
                    result,
                    f"{TOOL_RESULT_NOTE_SEPARATOR}[Loop guard: `{tool_name}` has now been called "
                    f"{repeat} times in a row with identical arguments. The result won't change — "
                    "reuse it and move on; an identical call made "
                    f"{LOOP_GUARD_STOP_REPEAT} times in a row will not be run.]",
                )
            return result

        identical_before, same_tool_before = self._prior_failures(delegation, call_key)
        identical = identical_before + 1
        same_tool = same_tool_before + 1
        note = self._warning_note(tool_name, identical, same_tool)
        if note:
            log.warning(
                f"{LogTag.AGENT} Loop guard warning appended",
                tool_name=tool_name,
                identical=identical,
                same_tool=same_tool,
            )
            self._append_note(result, note)
        return result

    @staticmethod
    def _delegation(request: ToolCallRequest) -> list[AnyMessage]:
        state = request.state
        if not isinstance(state, dict):
            raise TypeError(f"loop guard needs the graph state dict, got {type(state).__name__}")
        return current_delegation(cast(State, state))

    @classmethod
    def _repeat_streak(cls, delegation: Sequence[AnyMessage], call_key: _CallKey) -> int:
        """Count this delegation's latest model turns, newest first, that each issued this exact call.

        Includes the turn being executed; any turn without the call ends the streak.
        """
        streak = 0
        for message in reversed(delegation):
            if not isinstance(message, AIMessage):
                continue
            issued: list[ToolCall] = message.tool_calls
            if call_key not in {(call["name"], cls._args_key(call["args"])) for call in issued}:
                break
            streak += 1
        return streak

    @classmethod
    def _prior_failures(
        cls, delegation: Sequence[AnyMessage], call_key: _CallKey
    ) -> tuple[int, int]:
        """Return this call's trailing run of identical failures and its tool's failure count so far.

        A success or a different failing call ends the identical run; loop-guard
        refusals are not attempts and count as neither.
        """
        issued: dict[str, _CallKey] = {}
        identical = same_tool = 0
        for message in delegation:
            if isinstance(message, AIMessage):
                calls: list[ToolCall] = message.tool_calls
                issued.update(
                    {
                        call["id"]: (call["name"], cls._args_key(call["args"]))
                        for call in calls
                        if call["id"] is not None
                    }
                )
                continue
            if not isinstance(message, ToolMessage) or message.additional_kwargs.get(
                LOOP_GUARD_STOPPED_KEY
            ):
                continue
            key = issued.get(message.tool_call_id)
            if key is None:
                continue
            if message.status != "error":
                identical = 0
                continue
            identical = identical + 1 if key == call_key else 0
            if key[0] == call_key[0]:
                same_tool += 1
        return identical, same_tool

    def _warning_note(self, tool_name: str, identical: int, same_tool: int) -> str | None:
        """In-band note appended to an error result, or None below the thresholds."""
        if identical >= LOOP_GUARD_WARN_IDENTICAL:
            return (
                f"\n\n[Loop guard: this exact call to `{tool_name}` has now failed {identical} "
                "times in a row. Re-read the error above and change your arguments or approach — "
                "retrying it unchanged will keep failing.]"
            )
        if same_tool >= LOOP_GUARD_WARN_SAME_TOOL:
            return (
                f"\n\n[Loop guard: `{tool_name}` has failed {same_tool} times this run. Re-read the "
                "errors and reconsider your strategy instead of calling it again the same way.]"
            )
        return None

    @staticmethod
    def _append_note(result: ToolMessage, note: str) -> None:
        """Append the note to the error message's content in place.

        Tool errors from the DynamicToolNode carry string content; the list
        (content-block) form is handled defensively so the guard never drops a
        model's error text.
        """
        # Typed as `str | list[...]`, but kept as Any so the non-string, non-list
        # fallback below stays reachable rather than being narrowed away.
        content: Any = result.content
        if isinstance(content, str):
            result.content = content + note
        elif isinstance(content, list):
            result.content = [*content, note]
        else:
            result.content = f"{content}{note}"
        result.additional_kwargs = {
            **getattr(result, "additional_kwargs", {}),
            "loop_guard_warned": True,
        }

    @staticmethod
    def _args_key(args: object) -> str:
        try:
            serialized = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(args)
        return hashlib.md5(serialized.encode(), usedforsecurity=False).hexdigest()  # nosec B324
