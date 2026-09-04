"""bash + code mode: per-invocation token env injection.

The token must exist only in the launched command's env, only when code mode
is configured, and the client must be seeded first — no standing sandbox-wide
token, ever.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.coding.bash_tool import bash, build_bash_tool

MODULE = "app.agents.tools.coding.bash_tool"
CONFIG = {"configurable": {"user_id": "u1", "stream_id": "s1"}}
EXECUTE_ENV = {
    "GAIA_EXECUTE_URL": "https://api.test/api/v1/sandbox/execute",
    "GAIA_EXECUTE_TOKEN": "tok-1",
    "PYTHONPATH": "/workspace/.gaia",
}


def _sbx() -> AsyncMock:
    sbx = AsyncMock()
    sbx.sandbox_id = "sbx-9"
    sbx.commands = SimpleNamespace(
        run=AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="ok", stderr=""))
    )
    sbx.files = AsyncMock()
    return sbx


def _acquire(sbx: AsyncMock) -> MagicMock:
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=sbx)
    manager.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=manager)


@pytest.mark.unit
class TestBashExecuteEnv:
    async def test_configured_run_seeds_client_and_injects_scoped_env(self) -> None:
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()) as seed,
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV) as mint,
        ):
            await bash.ainvoke({"command": "python3 script.py", "timeout": 45}, config=CONFIG)
        seed.assert_awaited_once_with(sbx)
        run_kwargs = sbx.commands.run.await_args.kwargs
        assert run_kwargs["envs"]["GAIA_EXECUTE_TOKEN"] == "tok-1"
        mint_kwargs = mint.call_args.kwargs
        assert mint_kwargs["user_id"] == "u1"
        assert mint_kwargs["sandbox_id"] == "sbx-9"
        # TTL rides the command's own timeout, not a fixed long window.
        assert mint_kwargs["command_timeout_seconds"] == 45

    async def test_a_subagents_bash_carries_its_tool_space_into_the_token(self) -> None:
        """Code mode is the proxy's other door. Without the space in the token the
        route dispatched every call unconfined, so a subagent refused a tool by
        `execute` reached it with one line of python instead."""
        sbx = _sbx()
        scoped = build_bash_tool({"GMAIL_SEND_EMAIL": MagicMock(), "bash": MagicMock()})
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()),
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV) as mint,
        ):
            await scoped.ainvoke({"command": "python3 mine.py"}, config=CONFIG)
        assert mint.call_args.kwargs["scoped_tool_names"] == ["GMAIL_SEND_EMAIL", "bash"]

    async def test_the_executors_bash_is_unscoped(self) -> None:
        """The executor's space IS the registry — confining it would refuse tools
        it is entitled to run."""
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()),
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV) as mint,
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        assert mint.call_args.kwargs["scoped_tool_names"] is None

    async def test_unconfigured_run_injects_nothing(self) -> None:
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=False),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()) as seed,
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        seed.assert_not_awaited()
        assert sbx.commands.run.await_args.kwargs["envs"] == {}

    async def test_background_run_carries_the_env_too(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="12345\n", stderr="")
        )
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()),
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV),
        ):
            await bash.ainvoke({"command": "python3 long.py", "background": True}, config=CONFIG)
        assert sbx.commands.run.await_args.kwargs["envs"]["GAIA_EXECUTE_TOKEN"] == "tok-1"
