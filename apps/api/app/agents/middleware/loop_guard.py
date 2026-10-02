"""Tool-loop guardrail middleware.

Repeats: a call identical to the ones the model issued on its previous turns of
the current delegation is warned on the second turn and not run from the third,
in every run kind. The streak is read off the messages, so a new delegation on
the same thread starts clean. Failures: identical and same-tool failure tallies,
keyed by thread_id in a bounded LRU, append in-band notes; hard_stop mode also
stops a tool once it has failed LOOP_GUARD_STOP_SAME_TOOL times.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
import hashlib
import json
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langgraph.types import Command

from app.agents.middleware.completion import current_delegation
from app.constants.agents import TOOL_RESULT_NOTE_SEPARATOR
from app.constants.llm import (
    LOOP_GUARD_MAX_TRACKED_RUNS,
    LOOP_GUARD_STOP_REPEAT,
    LOOP_GUARD_STOP_SAME_TOOL,
    LOOP_GUARD_WARN_IDENTICAL,
    LOOP_GUARD_WARN_REPEAT,
    LOOP_GUARD_WARN_SAME_TOOL,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, runtime_configurable
from app.override.langgraph_bigtool.utils import State
from app.services.hil.utils import raw_tool_call
from shared.py.wide_events import log

_UNKNOWN_RUN = "unknown"


class _RunCounters:
    """Failure tallies for a single run (one thread_id)."""

    __slots__ = ("identical", "last_failure_key", "per_tool")

    def __init__(self) -> None:
        # (tool_name, args_hash) -> consecutive identical-argument failures
        self.identical: dict[tuple[str, str], int] = {}
        # The most recent failing (tool_name, args_hash), or None after a success.
        # Used to keep `identical` truly consecutive: any intervening success or a
        # different failing call breaks the streak.
        self.last_failure_key: tuple[str, str] | None = None
        # tool_name -> total failures for this tool this run
        self.per_tool: dict[str, int] = {}


class LoopGuardMiddleware(AgentMiddleware):
    """Refuse a model's repeated identical call; nudge (or, in hard_stop mode, halt) a failing tool.

    Usage::

        middleware = LoopGuardMiddleware(hard_stop=False)
    """

    def __init__(
        self,
        hard_stop: bool = False,
        max_tracked_runs: int = LOOP_GUARD_MAX_TRACKED_RUNS,
    ) -> None:
        super().__init__()
        self.hard_stop = hard_stop
        self._max_tracked_runs = max_tracked_runs
        self._runs: OrderedDict[str, _RunCounters] = OrderedDict()

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[str]]],
    ) -> ToolMessage | Command[str]:
        call = raw_tool_call(request)
        tool_name, tool_call_id = call.name, call.id
        failure_key = (tool_name, self._args_key(call.args))

        repeat = self._repeat_streak(request, failure_key)
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
                additional_kwargs={"loop_guard_stopped": True},
            )

        counters = self._counters_for(request)
        # Only carry the identical tally when the immediately-preceding failure was
        # this same call — a success or a different failing call in between resets
        # the "consecutive" streak.
        identical_before = (
            counters.identical.get(failure_key, 0)
            if counters.last_failure_key == failure_key
            else 0
        )
        same_tool_before = counters.per_tool.get(tool_name, 0)

        if self.hard_stop and same_tool_before >= LOOP_GUARD_STOP_SAME_TOOL:
            log.warning(
                f"{LogTag.AGENT} Loop guard hard-stopped tool — tool not executed",
                tool_name=tool_name,
                same_tool=same_tool_before,
            )
            return ToolMessage(
                content=(
                    f"[Loop guard] Blocked without executing: `{tool_name}` has already failed "
                    f"{same_tool_before} times this run (limit {LOOP_GUARD_STOP_SAME_TOOL}). This "
                    "tool is not working for the current task — stop calling it, re-read the "
                    "earlier errors, and try a different approach or step."
                ),
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
                additional_kwargs={"loop_guard_stopped": True},
            )

        result = await handler(request)
        # Only failures feed the loop counters; a success breaks the consecutive
        # streak (clears last_failure_key) so an alternating fail/succeed pattern
        # never trips the identical guard.
        if not isinstance(result, ToolMessage) or getattr(result, "status", None) != "error":
            counters.last_failure_key = None
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

        identical = identical_before + 1
        same_tool = same_tool_before + 1
        counters.identical[failure_key] = identical
        counters.last_failure_key = failure_key
        counters.per_tool[tool_name] = same_tool

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

    @classmethod
    def _repeat_streak(cls, request: ToolCallRequest, call_key: tuple[str, str]) -> int:
        """Count this delegation's latest model turns, newest first, that each issued this exact call.

        Includes the turn being executed; any turn without the call ends the streak.
        """
        state = request.state
        if not isinstance(state, dict):
            raise TypeError(f"loop guard needs the graph state dict, got {type(state).__name__}")
        streak = 0
        for message in reversed(current_delegation(cast(State, state))):
            if not isinstance(message, AIMessage):
                continue
            issued: list[ToolCall] = message.tool_calls
            if call_key not in {(call["name"], cls._args_key(call["args"])) for call in issued}:
                break
            streak += 1
        return streak

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

    def _counters_for(self, request: ToolCallRequest) -> _RunCounters:
        thread_id = self._thread_id(request)
        counters = self._runs.get(thread_id)
        if counters is None:
            counters = _RunCounters()
            self._runs[thread_id] = counters
            while len(self._runs) > self._max_tracked_runs:
                self._runs.popitem(last=False)
        else:
            self._runs.move_to_end(thread_id)
        return counters

    @staticmethod
    def _thread_id(request: ToolCallRequest) -> str:
        configurable: AgentConfigurable = runtime_configurable(request)
        return configurable.get("thread_id") or _UNKNOWN_RUN

    @staticmethod
    def _args_key(args: object) -> str:
        try:
            serialized = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(args)
        return hashlib.md5(serialized.encode(), usedforsecurity=False).hexdigest()  # nosec B324
