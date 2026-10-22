"""bash invocation: per-run code-mode token env injection and the run's contract.

The token must exist only in the launched command's env, only when code mode
is both env-configured AND flag-enabled for the user, and the client must be
seeded first — no standing sandbox-wide token, ever.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, ExitStack
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from tests.helpers import captured_wide_event

from app.agents.tools.coding._artifacts import artifact_links_note
from app.agents.tools.coding.bash_tool import _publish_artifacts, bash, build_bash_tool
from app.agents.workspace.paths import WORKSPACE_ROOT, runs_log_dir, session_dir
from app.constants.sandbox import (
    ARTIFACT_MTIME_SKEW_SECONDS,
    BASH_MAX_COMMAND_LENGTH,
    BASH_MAX_TIMEOUT_SECONDS,
)
from app.services.sandbox import SandboxAcquisitionError
from app.services.storage import ArtifactInfo, FsOps, fs_timer

ARTIFACTS_MODULE = "app.agents.tools.coding._artifacts"
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
            patch(f"{MODULE}._publish_artifacts", new=AsyncMock(return_value={})),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            await bash.ainvoke({"command": "make"}, config=SESSION_CONFIG)
        events = [c.args[0]["bash_data"] for c in emit.call_args_list]
        run_id = events[0]["id"]
        assert [e["status"] for e in events] == ["starting", "running", "running", "exited"]
        assert all(e["id"] == run_id for e in events)
        assert all(c.kwargs["session_id"] == "conv1" for c in emit.call_args_list)

    async def test_a_foreground_run_publishes_the_artifacts_it_made_and_a_background_one_does_not(
        self,
    ) -> None:
        # A command can write artifacts many ways (cat, python, mv), so the tool
        # enumerates them after every foreground run; a detached one has not run yet.
        publish = AsyncMock(return_value={})
        foreground = _sbx()
        foreground.commands.run = _streaming_run()
        background = _sbx()
        background.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="12345\n", stderr="")
        )
        with patch(f"{MODULE}._publish_artifacts", new=publish):
            with patch(f"{MODULE}.acquire_sandbox", new=_acquire(foreground)):
                await bash.ainvoke({"command": "make"}, config=SESSION_CONFIG)
            with patch(f"{MODULE}.acquire_sandbox", new=_acquire(background)):
                await bash.ainvoke(
                    {"command": "sleep 99", "background": True}, config=SESSION_CONFIG
                )
        publish.assert_awaited_once()
        assert publish.await_args.args == (foreground, "u1", "conv1")

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


SHORT_URL = "https://heygaia.link/abcdefghijk"
RUN_STARTED_AT = 1_700_000_000.0
ARTIFACT_SIZE = 3


def _artifact_listing(*records: tuple[str, float]) -> str:
    """Build the NUL-delimited find stream _publish_artifacts parses (path, size, mtime, body)."""
    return "".join(f"{rel}\0{ARTIFACT_SIZE}\0{mtime}\0\0" for rel, mtime in records)


@pytest.mark.unit
class TestBashArtifactLinks:
    async def test_the_result_hands_the_agent_the_links_of_what_the_run_wrote(self) -> None:
        sbx = _sbx()
        publish = AsyncMock(return_value={"report.html": SHORT_URL})
        timed: list[str] = []

        def recording_timer(op: str, **labels: str) -> AbstractAsyncContextManager[None]:
            timed.append(op)
            return fs_timer(op, **labels)

        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}._publish_artifacts", new=publish),
            patch(f"{MODULE}.fs_timer", new=recording_timer),
        ):
            before = time.time()
            out = await bash.ainvoke({"command": "make"}, config=SESSION_CONFIG)
            after = time.time()
        assert out.endswith(artifact_links_note({"report.html": SHORT_URL}))
        assert FsOps.TOOL_BASH_PUBLISH in timed
        assert publish.await_args.args == (sbx, "u1", "conv1")
        assert before <= publish.await_args.kwargs["changed_since"] <= after

    async def test_a_run_outside_a_session_publishes_nothing(self) -> None:
        sbx = _sbx()
        publish = AsyncMock(return_value={"report.html": SHORT_URL})
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}._publish_artifacts", new=publish),
        ):
            out = await bash.ainvoke({"command": "make"}, config=CONFIG)
        publish.assert_not_awaited()
        assert SHORT_URL not in out

    async def test_only_files_written_since_the_run_started_get_a_link(self) -> None:
        sbx = _sbx()
        boundary = RUN_STARTED_AT - ARTIFACT_MTIME_SKEW_SECONDS
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(
                stdout=_artifact_listing(
                    ("old.md", boundary - 0.5),
                    ("skewed.md", boundary),
                    ("new.md", RUN_STARTED_AT + 1),
                )
            )
        )
        with (
            patch(
                f"{ARTIFACTS_MODULE}.optional_short_link", new=AsyncMock(return_value=SHORT_URL)
            ) as mint,
            patch(f"{ARTIFACTS_MODULE}.publish_artifact_event", new=AsyncMock()) as pub,
        ):
            links = await _publish_artifacts(sbx, "u1", "conv1", changed_since=RUN_STARTED_AT)
        assert links == {"skewed.md": SHORT_URL, "new.md": SHORT_URL}
        # Only what the run wrote is shared; listing an older file never mints for it.
        assert [c.args[2] for c in mint.await_args_list] == ["conv1/skewed.md", "conv1/new.md"]
        # Every artifact is still published, linked or not, so its card stays live.
        assert [c.args[1]["path"] for c in pub.await_args_list] == [
            "old.md",
            "skewed.md",
            "new.md",
        ]
        assert "short_url" not in pub.await_args_list[0].args[1]

    async def test_a_file_whose_publish_failed_gets_no_link(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(stdout=_artifact_listing(("new.md", RUN_STARTED_AT)))
        )
        with patch(f"{MODULE}.publish_artifact", new=AsyncMock(return_value=None)):
            links = await _publish_artifacts(sbx, "u1", "conv1", changed_since=RUN_STARTED_AT)
        assert links == {}

    async def test_each_artifact_is_published_with_its_size_mtime_and_inline_body(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(
                stdout=f"notes.md\0{ARTIFACT_SIZE}\0{RUN_STARTED_AT}\0YWJj\0"
            )
        )
        with patch(f"{MODULE}.publish_artifact", new=AsyncMock(return_value=SHORT_URL)) as pub:
            await _publish_artifacts(sbx, "u1", "conv1", changed_since=RUN_STARTED_AT)
        pub.assert_awaited_once_with(
            "u1",
            "conv1",
            ArtifactInfo(
                path="notes.md",
                size_bytes=ARTIFACT_SIZE,
                mtime=RUN_STARTED_AT,
                content_type="text/markdown",
            ),
            "abc",
            written_this_turn=True,
        )


def _error_event(run_id: str, chunk: str, session_id: str | None) -> object:
    return call(
        {
            "bash_data": {
                "id": run_id,
                "status": "error",
                "exit_code": None,
                "stream": "stderr",
                "chunk": chunk,
            }
        },
        session_id=session_id,
    )


@pytest.mark.unit
class TestBashRequestValidation:
    async def test_a_whitespace_only_command_is_refused_before_any_sandbox(self) -> None:
        acquire = _acquire(_sbx())
        with patch(f"{MODULE}.acquire_sandbox", new=acquire):
            out = await bash.ainvoke({"command": "   "}, config=CONFIG)
        assert out == "Error: command cannot be empty"
        acquire.assert_not_called()

    async def test_a_command_at_the_length_cap_runs(self) -> None:
        sbx = _sbx()
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)):
            out = await bash.ainvoke({"command": "x" * BASH_MAX_COMMAND_LENGTH}, config=CONFIG)
        assert out == "exit_code: 0\n\nstdout:\nok"

    async def test_a_command_past_the_length_cap_is_refused(self) -> None:
        acquire = _acquire(_sbx())
        with patch(f"{MODULE}.acquire_sandbox", new=acquire):
            out = await bash.ainvoke(
                {"command": "x" * (BASH_MAX_COMMAND_LENGTH + 1)}, config=CONFIG
            )
        assert out == f"Error: command exceeds {BASH_MAX_COMMAND_LENGTH} characters"
        acquire.assert_not_called()

    async def test_a_one_second_timeout_is_kept_as_the_server_deadline(self) -> None:
        sbx = _sbx()
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)):
            await bash.ainvoke({"command": "echo hi", "timeout": 1}, config=CONFIG)
        assert sbx.commands.run.await_args.kwargs["timeout"] == 1

    async def test_a_session_call_without_cwd_runs_in_the_session_root(self) -> None:
        sbx = _sbx()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}._publish_artifacts", new=AsyncMock(return_value={})),
        ):
            await bash.ainvoke({"command": "pwd"}, config=SESSION_CONFIG)
        assert sbx.commands.run.await_args.kwargs["cwd"] == session_dir("conv1")


@pytest.mark.unit
class TestBashRunTelemetry:
    async def test_the_call_is_tagged_as_a_bash_execute_on_the_wide_event(self) -> None:
        with patch(f"{MODULE}.acquire_sandbox", new=_acquire(_sbx())):
            async with captured_wide_event() as fields:
                await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        assert fields["tool"] == {"name": "bash", "action": "execute"}

    async def test_the_starting_event_names_the_command_and_the_workspace_root(self) -> None:
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(_sbx())),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            await bash.ainvoke({"command": "echo hi"}, config=CONFIG)
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        assert emit.call_args_list[0] == call(
            {
                "bash_data": {
                    "id": run_id,
                    "command": "echo hi",
                    "cwd": WORKSPACE_ROOT,
                    "status": "starting",
                }
            },
            session_id=None,
        )

    async def test_the_sandbox_is_acquired_for_the_caller_and_both_phases_are_timed(
        self,
    ) -> None:
        acquire = _acquire(_sbx())
        timer = MagicMock(wraps=fs_timer)
        with (
            patch(f"{MODULE}.acquire_sandbox", new=acquire),
            patch(f"{MODULE}._publish_artifacts", new=AsyncMock(return_value={})),
            patch(f"{MODULE}.fs_timer", new=timer),
        ):
            await bash.ainvoke({"command": "echo hi"}, config=SESSION_CONFIG)
        acquire.assert_called_once_with("u1")
        assert timer.call_args_list == [call(FsOps.TOOL_BASH), call(FsOps.TOOL_BASH_PUBLISH)]


@pytest.mark.unit
class TestBashFailures:
    async def test_an_unavailable_sandbox_is_reported_and_ends_the_stream(self) -> None:
        acquire = MagicMock(side_effect=SandboxAcquisitionError("no capacity"))
        with (
            patch(f"{MODULE}.acquire_sandbox", new=acquire),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            out = await bash.ainvoke({"command": "echo hi"}, config=SESSION_CONFIG)
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        assert out == "Error: sandbox unavailable (no capacity)"
        assert emit.call_args_list[-1] == _error_event(run_id, "no capacity", "conv1")

    async def test_a_crashed_command_is_reported_and_ends_the_stream(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            out = await bash.ainvoke({"command": "echo hi"}, config=SESSION_CONFIG)
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        assert out == "Error executing command: boom"
        assert emit.call_args_list[-1] == _error_event(run_id, "boom", "conv1")

    async def test_a_background_launch_with_no_pid_or_stderr_is_reported(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout=""))
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            out = await bash.ainvoke(
                {"command": "sleep 99", "background": True}, config=SESSION_CONFIG
            )
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        reason = "failed to start background command (stderr: )"
        assert out == f"Error: {reason}"
        assert emit.call_args_list[-1] == _error_event(run_id, reason, "conv1")
