"""A real executor resume arms the checkpoint probe; a fresh run does not.

``_execute_executor`` stamping ``HIL_RESUME_CONFIG_KEY`` on a resume is the only
thing that makes handoff/spawn recovery reachable in production — every replay
guard downstream keys on it. Nothing else exercised these two lines: the e2e
drivers patch the re-dispatch seam and the replay tests set the flag by hand,
so deleting the stamp would fail nothing while silently re-running finished
subagents' side effects on every real resume.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langgraph.types import Command

from app.agents.core.background.executor_runner import _execute_executor
from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.constants.hil import HIL_RESUME_CONFIG_KEY

RUNNER = "app.agents.core.background.executor_runner"


class _Ctx:
    def __init__(self) -> None:
        self.configurable: dict[str, Any] = {"conversation_id": "conv-1"}
        self.config: dict[str, Any] = {"configurable": {"conversation_id": "conv-1"}}


async def _run(resume: Command | None) -> _Ctx:
    ctx = _Ctx()
    execute = AsyncMock(return_value=SubagentOutcome(text="done"))
    with (
        patch(f"{RUNNER}.prepare_executor_execution", AsyncMock(return_value=(ctx, None))),
        patch(f"{RUNNER}.make_redis_stream_writer", lambda _stream_id: None),
        patch(f"{RUNNER}.execute_subagent_stream", execute),
    ):
        await _execute_executor("task", {"user_id": "u1"}, "stream-1", resume=resume)
    assert execute.await_count == 1
    assert execute.await_args.kwargs["ctx"] is ctx
    return ctx


async def test_a_resume_stamps_the_replay_flag_on_both_config_surfaces() -> None:
    # Both, because the handoff tool reads configurable while build_agent_config
    # derives child configs from config["configurable"] — one without the other
    # leaves half the replay guards unarmed.
    ctx = await _run(resume=Command(resume={"status": "approved"}))

    assert ctx.configurable.get(HIL_RESUME_CONFIG_KEY) is True
    assert ctx.config["configurable"].get(HIL_RESUME_CONFIG_KEY) is True


async def test_a_fresh_run_does_not_arm_the_probe() -> None:
    # The probe is a per-handoff Postgres read; fresh runs (effectively all of
    # them) must skip it.
    ctx = await _run(resume=None)

    assert HIL_RESUME_CONFIG_KEY not in ctx.configurable
    assert HIL_RESUME_CONFIG_KEY not in ctx.config["configurable"]
