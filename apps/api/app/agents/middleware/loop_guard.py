"""Tool-loop guardrail middleware.

Detects a model stuck retrying a failing tool call and nudges it to change
strategy. Two failure signals are tracked per run:

- Identical failures: the same tool called with the same arguments keeps
  returning ``status="error"``. Almost always a genuine dead end (bad URL,
  missing permission) the model is blind to.
- Same-tool failures: one tool fails repeatedly across the run regardless of
  arguments — a weaker signal that the chosen approach isn't working.

Behaviour is escalating:

- At the warn thresholds, a short note is appended to the error ToolMessage so
  the model sees, in-band, that it is looping and should change course.
- In ``hard_stop`` mode (silent / workflow runs, where no human is watching to
  interrupt a runaway), once the stop thresholds are hit the offending tool is
  no longer executed at all — a synthetic error is returned instead, capping
  wasted tool calls and cost.

Counters are keyed by the run's ``thread_id`` (not the middleware instance),
because the graph — and therefore this middleware — is a per-process singleton
cached by the lazy provider; per-instance dicts would otherwise leak failures
across unrelated runs and users. A bounded LRU over recent threads keeps memory
flat.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
import hashlib
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.constants.llm import (
    LOOP_GUARD_MAX_TRACKED_RUNS,
    LOOP_GUARD_STOP_IDENTICAL,
    LOOP_GUARD_STOP_REPEAT,
    LOOP_GUARD_STOP_SAME_TOOL,
    LOOP_GUARD_WARN_IDENTICAL,
    LOOP_GUARD_WARN_REPEAT,
    LOOP_GUARD_WARN_SAME_TOOL,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import runtime_configurable
from shared.py.wide_events import log

_UNKNOWN_RUN = "unknown"


class _RunCounters:
    """Failure tallies for a single run (one ``thread_id``)."""

    __slots__ = ("identical", "last_call_key", "last_failure_key", "per_tool", "repeat")

    def __init__(self) -> None:
        # (tool_name, args_hash) -> consecutive identical-argument failures
        self.identical: dict[tuple[str, str], int] = {}
        # The most recent failing (tool_name, args_hash), or None after a success.
        # Used to keep `identical` truly consecutive: any intervening success or a
        # different failing call breaks the streak.
        self.last_failure_key: tuple[str, str] | None = None
        # tool_name -> total failures for this tool this run
        self.per_tool: dict[str, int] = {}
        # The most recent call's (tool_name, args_hash), regardless of outcome,
        # and how many times in a row it has been made. Counts redundant duplicate
        # calls (a re-issued handoff, the exact same search) that a weak model
        # loops on even when they *succeed* — the failure counters never see those.
        self.last_call_key: tuple[str, str] | None = None
        self.repeat: int = 0


class LoopGuardMiddleware(AgentMiddleware):
    """Nudge (or, in ``hard_stop`` mode, halt) a model looping on a failing tool.

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
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_call = request.tool_call
        tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else tool_call.name
        tool_call_id = tool_call.get("id", "") if isinstance(tool_call, dict) else tool_call.id
        args = tool_call.get("args", {}) if isinstance(tool_call, dict) else tool_call.args
        args_key = self._args_key(args)
        failure_key = (tool_name, args_key)

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

        # Consecutive identical calls, regardless of outcome (redundant duplicates).
        if counters.last_call_key == failure_key:
            counters.repeat += 1
        else:
            counters.last_call_key = failure_key
            counters.repeat = 1
        repeat = counters.repeat

        if self.hard_stop:
            # The failure-specific stop is checked FIRST because it is the more
            # specific diagnosis and says so ("already failed N times"). A run of
            # identical FAILING calls trips both counters on the same call, so
            # checking repeat first would shadow that message with the generic
            # duplicate one and leave the model less to act on.
            stopped = self._hard_stop_message(
                tool_name, tool_call_id, identical_before, same_tool_before
            )
            if stopped is not None:
                log.warning(
                    f"{LogTag.AGENT} Loop guard hard-stopped tool — tool not executed",
                    tool_name=tool_name,
                    identical=identical_before,
                    same_tool=same_tool_before,
                )
                return stopped

            if repeat >= LOOP_GUARD_STOP_REPEAT:
                log.warning(
                    f"{LogTag.AGENT} Loop guard hard-stopped tool — redundant duplicate call not executed",
                    tool_name=tool_name,
                    repeat=repeat,
                )
                return ToolMessage(
                    content=(
                        f"[Loop guard] Blocked without executing: `{tool_name}` has already been "
                        f"called {repeat} times in a row with identical arguments (limit "
                        f"{LOOP_GUARD_STOP_REPEAT}). Re-running it will return the same result — "
                        "reuse the earlier result, or if the task is done, stop and report it."
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
                    f"\n\n[Loop guard: `{tool_name}` has now been called {repeat} times in a row "
                    "with identical arguments. The result won't change — reuse the earlier result "
                    "and move on instead of repeating this call.]",
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

    def _hard_stop_message(
        self, tool_name: str, tool_call_id: str, identical: int, same_tool: int
    ) -> ToolMessage | None:
        """Return a synthetic error to send *instead of* running the tool, or None."""
        if identical >= LOOP_GUARD_STOP_IDENTICAL:
            content = (
                f"[Loop guard] Blocked without executing: `{tool_name}` has already failed "
                f"{identical} times this run with identical arguments (limit {LOOP_GUARD_STOP_IDENTICAL}). "
                "This call will keep failing — stop retrying it, re-read the earlier errors, and "
                "either change the arguments/approach or move on to a different step."
            )
        elif same_tool >= LOOP_GUARD_STOP_SAME_TOOL:
            content = (
                f"[Loop guard] Blocked without executing: `{tool_name}` has already failed "
                f"{same_tool} times this run (limit {LOOP_GUARD_STOP_SAME_TOOL}). This tool is not "
                "working for the current task — stop calling it, re-read the earlier errors, and try "
                "a different approach or step."
            )
        else:
            return None
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
            additional_kwargs={"loop_guard_stopped": True},
        )

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
        return runtime_configurable(request).get("thread_id") or _UNKNOWN_RUN

    @staticmethod
    def _args_key(args: object) -> str:
        try:
            serialized = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(args)
        return hashlib.md5(serialized.encode(), usedforsecurity=False).hexdigest()  # nosec B324
