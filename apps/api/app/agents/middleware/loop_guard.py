"""Tool-loop guardrail middleware.

Tracks identical failures (same tool + args returning status="error"),
same-tool failures, and repeats (the same tool + args issued again this run,
whatever the outcome). Warn thresholds append an in-band note to the
ToolMessage; in a background run (no user present) stop thresholds skip the
call and return a synthetic error. Interactive runs only warn.

Counters are keyed by run (thread_id + root_request_id): the graph is a
per-process singleton, and the executor keeps one thread per conversation
across every turn and scheduled run. A bounded LRU keeps memory flat.
retrieve_tools runs in the select_tools node, which consults this same guard.
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

from app.constants.agents import TOOL_RESULT_NOTE_SEPARATOR
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
from app.models.agent_models import AgentConfigurable, runtime_configurable
from app.services.hil.utils import raw_tool_call
from shared.py.wide_events import log

_UNKNOWN_RUN = "unknown"

#: (thread_id, root_request_id): one run of one graph thread.
RunKey = tuple[str, str]


class _RunCounters:
    """Call and failure tallies for a single run."""

    __slots__ = ("calls", "identical", "last_failure_key", "per_tool")

    def __init__(self) -> None:
        # (tool_name, args_hash) -> consecutive identical-argument failures
        self.identical: dict[tuple[str, str], int] = {}
        # The most recent failing (tool_name, args_hash), or None after a success.
        # Used to keep `identical` truly consecutive: any intervening success or a
        # different failing call breaks the streak.
        self.last_failure_key: tuple[str, str] | None = None
        # tool_name -> total failures for this tool this run
        self.per_tool: dict[str, int] = {}
        # (tool_name, args_hash) -> times issued this run, whatever the outcome,
        # consecutive or not: interleaving reset a consecutive-only count while a
        # live run issued one query 14 times.
        self.calls: dict[tuple[str, str], int] = {}


class LoopGuardMiddleware(AgentMiddleware):
    """Nudge a model looping on a tool call; halt it in a background run.

    Blocking is decided per call from the run's execution_mode: the executor
    graph is one per-process singleton shared by both run kinds.
    """

    def __init__(self, max_tracked_runs: int = LOOP_GUARD_MAX_TRACKED_RUNS) -> None:
        super().__init__()
        self._max_tracked_runs = max_tracked_runs
        self._runs: OrderedDict[RunKey, _RunCounters] = OrderedDict()

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[str]]],
    ) -> ToolMessage | Command[str]:
        call = raw_tool_call(request)
        tool_name, tool_call_id = call.name, call.id
        args_key = self._args_key(call.args)
        failure_key = (tool_name, args_key)

        configurable: AgentConfigurable = runtime_configurable(request)
        counters = self._counters_for(self._run_key(configurable))
        # Only carry the identical tally when the immediately-preceding failure was
        # this same call — a success or a different failing call in between resets
        # the "consecutive" streak.
        identical_before = (
            counters.identical.get(failure_key, 0)
            if counters.last_failure_key == failure_key
            else 0
        )
        same_tool_before = counters.per_tool.get(tool_name, 0)

        # Identical calls this run, regardless of outcome (redundant duplicates).
        repeat = counters.calls.get(failure_key, 0) + 1
        counters.calls[failure_key] = repeat

        # Only a background run has no user to be surprised by a refused call.
        if configurable.get("execution_mode") == "background":
            # Failure-specific stop is checked FIRST: it's the more specific
            # diagnosis, and checking repeat first would shadow it with the
            # generic duplicate message on a run of identical failing calls.
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
                        f"called {repeat} times this run with identical arguments (limit "
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
                    f"{TOOL_RESULT_NOTE_SEPARATOR}[Loop guard: `{tool_name}` has now been called "
                    f"{repeat} times this run "
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

    def _counters_for(self, run_key: RunKey) -> _RunCounters:
        counters = self._runs.get(run_key)
        if counters is None:
            counters = _RunCounters()
            self._runs[run_key] = counters
            while len(self._runs) > self._max_tracked_runs:
                self._runs.popitem(last=False)
        else:
            self._runs.move_to_end(run_key)
        return counters

    @staticmethod
    def _run_key(configurable: AgentConfigurable) -> RunKey:
        return (
            configurable.get("thread_id") or _UNKNOWN_RUN,
            configurable.get("root_request_id") or _UNKNOWN_RUN,
        )

    @staticmethod
    def _args_key(args: object) -> str:
        try:
            serialized = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(args)
        return hashlib.md5(serialized.encode(), usedforsecurity=False).hexdigest()  # nosec B324
