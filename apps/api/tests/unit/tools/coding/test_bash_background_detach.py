"""bash background=True must return while the command keeps running, on a real shell."""

from __future__ import annotations

import os
import signal

import pytest
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox

from app.agents.tools.coding import bash_tool


@pytest.mark.unit
async def test_background_launch_returns_while_a_long_command_keeps_running() -> None:
    """Regression: mkdir && nohup ... & backgrounded the whole list, holding stdout open."""
    fake = FakeAsyncSandbox()
    run = bash_tool._BashInvocation(
        user_id="u1",
        run_id="detach1",
        command="sleep 30",
        cwd="/workspace",
        timeout=30,
        background=True,
        session_id=None,
        config={"configurable": {}},
        scoped_tools=None,
    )

    out = await bash_tool._run_background(fake, run)

    assert out.startswith("Started in background. pid=")
    pid = int(out.split("pid=", 1)[1].split(",", 1)[0])
    try:
        os.kill(pid, 0)
    finally:
        os.kill(pid, signal.SIGTERM)
