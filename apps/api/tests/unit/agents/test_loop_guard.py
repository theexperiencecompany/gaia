"""LoopGuardMiddleware: consecutive-identical-call (repeat) detection.

The pre-existing guard only reacts to status="error" results. These tests cover
the added signal: a call repeated with identical arguments that *succeeds* is
still a loop (a re-issued handoff, the same search fired again), and must be
warned in-band (interactive) or blocked before executing (hard_stop runs).
"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
import pytest

from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.constants.llm import LOOP_GUARD_STOP_REPEAT, LOOP_GUARD_WARN_REPEAT


def _request(name: str, args: dict, thread_id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": name, "args": args, "id": f"call_{name}"},
        runtime=SimpleNamespace(config={"configurable": {"thread_id": thread_id}}),
    )


def _ok_handler(content: str = "ok"):
    async def handler(request):
        return ToolMessage(
            content=content, tool_call_id=request.tool_call["id"], name=request.tool_call["name"]
        )

    return handler


class TestLoopGuardRepeat:
    async def test_identical_successful_calls_get_warned(self):
        guard = LoopGuardMiddleware(hard_stop=False)
        handler = _ok_handler()
        req = _request("handoff", {"subagent_id": "gmail", "task": "triage"})

        results = []
        for _ in range(LOOP_GUARD_WARN_REPEAT):
            results.append(await guard.awrap_tool_call(req, handler))

        # Calls before the threshold carry no note; the threshold-th one does.
        assert "[Loop guard:" not in results[0].content
        assert "called" in results[-1].content and "in a row" in results[-1].content
        assert results[-1].additional_kwargs.get("loop_guard_warned") is True

    async def test_different_args_reset_the_repeat_streak(self):
        guard = LoopGuardMiddleware(hard_stop=False)
        handler = _ok_handler()

        for i in range(LOOP_GUARD_WARN_REPEAT + 2):
            # Vary the args every call — never a duplicate, so never a repeat warn.
            res = await guard.awrap_tool_call(_request("search", {"q": f"query-{i}"}), handler)
            assert "[Loop guard:" not in res.content

    async def test_hard_stop_blocks_redundant_call_without_executing(self):
        guard = LoopGuardMiddleware(hard_stop=True)
        executed = {"count": 0}

        async def counting_handler(request):
            executed["count"] += 1
            return ToolMessage(
                content="ok", tool_call_id=request.tool_call["id"], name=request.tool_call["name"]
            )

        req = _request("handoff", {"subagent_id": "gmail", "task": "triage"})
        last = None
        for _ in range(LOOP_GUARD_STOP_REPEAT):
            last = await guard.awrap_tool_call(req, counting_handler)

        # The STOP_REPEAT-th call is blocked before execution.
        assert executed["count"] == LOOP_GUARD_STOP_REPEAT - 1, (
            "the redundant call at the stop threshold must not execute"
        )
        assert last.additional_kwargs.get("loop_guard_stopped") is True
        assert last.status == "error"

    async def test_repeat_streak_is_per_thread(self):
        guard = LoopGuardMiddleware(hard_stop=False)
        handler = _ok_handler()
        args = {"subagent_id": "gmail", "task": "triage"}

        # Interleave two threads making the same call; neither should reach the
        # warn threshold because each thread's streak is only 1 then 2.
        for _ in range(2):
            r_a = await guard.awrap_tool_call(_request("handoff", args, "thread-a"), handler)
            r_b = await guard.awrap_tool_call(_request("handoff", args, "thread-b"), handler)
            assert "[Loop guard:" not in r_a.content
            assert "[Loop guard:" not in r_b.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
