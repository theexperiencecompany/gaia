"""bash invocation: per-run code-mode token env injection and the run's contract.

The token must exist only in the launched command's env, only when code mode
is both env-configured AND flag-enabled for the user, and the client must be
seeded first — no standing sandbox-wide token, ever.
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.coding.bash_tool import bash, build_bash_tool
from app.agents.workspace.paths import WORKSPACE_ROOT, runs_log_dir
from app.constants.sandbox import BASH_MAX_TIMEOUT_SECONDS

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


def _code_mode_on(mint: MagicMock) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(patch(f"{MODULE}.sandbox_execute_enabled", return_value=True))
    stack.enter_context(patch(f"{MODULE}.is_code_mode_enabled", return_value=True))
    stack.enter_context(patch(f"{MODULE}.seed_execute_client", new=AsyncMock()))
    stack.enter_context(patch(f"{MODULE}.mint_execute_env", new=mint))
    return stack


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
            patch(f"{MODULE}.is_code_mode_enabled", return_value=True),
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
        """Code mode is the proxy's other door."""
        sbx = _sbx()
        scoped = build_bash_tool({"GMAIL_SEND_EMAIL": MagicMock(), "bash": MagicMock()})
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.is_code_mode_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()),
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV) as mint,
        ):
            await scoped.ainvoke({"command": "python3 mine.py"}, config=CONFIG)
        assert mint.call_args.kwargs["scoped_tool_names"] == ["GMAIL_SEND_EMAIL", "bash"]

    async def test_the_executors_bash_is_unscoped(self) -> None:
        """The executor's space IS the registry — confining it would refuse tools it is entitled to run."""
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.is_code_mode_enabled", return_value=True),
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

    async def test_flag_off_mints_nothing_despite_env_config(self) -> None:
        """The per-user flag is the rollout gate: env-configured but unflagged runs bash with no execute env, same as unconfigured."""
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.is_code_mode_enabled", return_value=False),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()) as seed,
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV) as mint,
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        seed.assert_not_awaited()
        mint.assert_not_called()
        assert sbx.commands.run.await_args.kwargs["envs"] == {}

    async def test_background_run_carries_the_env_too(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="12345\n", stderr="")
        )
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.is_code_mode_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()),
            patch(f"{MODULE}.mint_execute_env", return_value=EXECUTE_ENV),
        ):
            await bash.ainvoke({"command": "python3 long.py", "background": True}, config=CONFIG)
        assert sbx.commands.run.await_args.kwargs["envs"]["GAIA_EXECUTE_TOKEN"] == "tok-1"

    async def test_code_mode_flag_is_read_for_the_invoking_user(self) -> None:
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.is_code_mode_enabled", return_value=False) as flag,
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        flag.assert_awaited_once_with("u1")

    async def test_token_is_minted_for_this_run_and_this_callers_config(self) -> None:
        sbx = _sbx()
        mint = MagicMock(return_value=EXECUTE_ENV)
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.safe_emit") as emit,
            _code_mode_on(mint),
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        assert mint.call_args.kwargs["run_id"] == run_id
        assert mint.call_args.kwargs["config"]["configurable"]["user_id"] == "u1"

    async def test_a_sandbox_without_an_id_still_mints(self) -> None:
        sbx = SimpleNamespace(
            commands=SimpleNamespace(
                run=AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="ok", stderr=""))
            ),
            files=AsyncMock(),
        )
        mint = MagicMock(return_value=EXECUTE_ENV)
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)), _code_mode_on(mint):
            out = await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        assert out.startswith("exit_code: 0")
        assert mint.call_args.kwargs["sandbox_id"] is None

    async def test_background_token_lives_for_the_max_window_not_the_command_timeout(
        self,
    ) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="12345\n", stderr="")
        )
        mint = MagicMock(return_value=EXECUTE_ENV)
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)), _code_mode_on(mint):
            await bash.ainvoke(
                {"command": "python3 long.py", "background": True, "timeout": 45}, config=CONFIG
            )
        assert mint.call_args.kwargs["command_timeout_seconds"] == BASH_MAX_TIMEOUT_SECONDS


SESSION_CONFIG = {"configurable": {"user_id": "u1", "conversation_id": "conv1"}}


def _streaming_run(stdout: str = "out", stderr: str = "err") -> AsyncMock:
    async def run(command: str, **kwargs: Any) -> SimpleNamespace:
        kwargs["on_stdout"](stdout)
        kwargs["on_stderr"](stderr)
        return SimpleNamespace(exit_code=0, stdout=stdout, stderr=stderr)

    return AsyncMock(side_effect=run)


SPACES = [None, {"GMAIL_SEND_EMAIL": MagicMock(), "bash": MagicMock()}]


@pytest.mark.unit
class TestBashRunContract:
    @pytest.mark.parametrize("space", SPACES, ids=["executor", "subagent"])
    async def test_a_call_with_no_options_runs_in_the_foreground_at_the_workspace_root(
        self,
        space: dict[str, MagicMock] | None,
    ) -> None:
        sbx = _sbx()
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)):
            out = await build_bash_tool(space).ainvoke({"command": "echo hi"}, config=CONFIG)
        assert out.startswith("exit_code: 0")
        assert sbx.commands.run.await_args.args[0] == "echo hi"
        assert sbx.commands.run.await_args.kwargs["cwd"] == WORKSPACE_ROOT

    @pytest.mark.parametrize("space", SPACES, ids=["executor", "subagent"])
    async def test_an_explicit_cwd_is_where_the_command_runs(
        self, space: dict[str, MagicMock] | None
    ) -> None:
        sbx = _sbx()
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)):
            await build_bash_tool(space).ainvoke(
                {"command": "ls", "cwd": "/workspace/proj"}, config=CONFIG
            )
        sbx.files.make_dir.assert_awaited_once_with("/workspace/proj")
        assert sbx.commands.run.await_args.kwargs["cwd"] == "/workspace/proj"

    @pytest.mark.parametrize("space", SPACES, ids=["executor", "subagent"])
    async def test_a_background_launch_runs_in_its_cwd_with_the_short_launcher_deadline(
        self,
        space: dict[str, MagicMock] | None,
    ) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="12345\n", stderr="")
        )
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)):
            out = await build_bash_tool(space).ainvoke(
                {
                    "command": "sleep 99",
                    "cwd": "/workspace/proj",
                    "background": True,
                    "timeout": 300,
                },
                config=CONFIG,
            )
        assert "pid=12345" in out
        launch = sbx.commands.run.await_args.kwargs
        assert launch["cwd"] == "/workspace/proj"
        assert launch["timeout"] == 10

    async def test_every_foreground_event_carries_the_runs_id_and_session(self) -> None:
        sbx = _sbx()
        sbx.commands.run = _streaming_run()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}._publish_artifacts", new=AsyncMock()),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            await bash.ainvoke({"command": "make"}, config=SESSION_CONFIG)
        events = [c.args[0]["bash_data"] for c in emit.call_args_list]
        run_id = events[0]["id"]
        assert [e["status"] for e in events] == ["starting", "running", "running", "exited"]
        assert all(e["id"] == run_id for e in events)
        assert all(c.kwargs["session_id"] == "conv1" for c in emit.call_args_list)

    async def test_the_background_started_event_carries_the_runs_id(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="12345\n", stderr="")
        )
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            await bash.ainvoke({"command": "sleep 99", "background": True}, config=SESSION_CONFIG)
        starting, started = (c.args[0]["bash_data"] for c in emit.call_args_list)
        assert started["status"] == "background_started"
        assert started["id"] == starting["id"]

    async def test_full_foreground_output_is_persisted_under_the_runs_id(self) -> None:
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        path, body = sbx.files.write.await_args.args
        assert path == f"{runs_log_dir()}/{run_id}.log"
        assert body.startswith("ok")
