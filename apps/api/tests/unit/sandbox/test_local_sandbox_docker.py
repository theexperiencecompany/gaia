"""Live-daemon tests for LocalDockerSandbox — the real `docker exec` path.

The hermetic sibling (`test_local_sandbox.py`) proves argv/exception wiring
against fakes; these prove the actual contract against a real Docker daemon:
commands execute, files round-trip byte-exact through tar+cp, and missing
paths raise e2b's NotFoundException. Skipped automatically wherever the docker
CLI is unavailable (CI sandboxes without a daemon).

Each test gets its own uniquely-named container, torn down on exit.
"""

from __future__ import annotations

import shutil
from typing import Any
import uuid

import pytest

from app.config.settings import settings
from app.services.sandbox.local_sandbox import LocalDockerSandbox

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="requires the docker CLI + daemon"
)


def _uid() -> str:
    return f"lsbx-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def sbx() -> LocalDockerSandbox:
    sandbox = LocalDockerSandbox(_uid())
    await sandbox.ensure_started()
    try:
        yield sandbox
    finally:
        await sandbox.kill()


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


async def test_a_command_runs_and_captures_output(sbx: LocalDockerSandbox) -> None:
    result = await sbx.commands.run("echo hello-local", cwd="/workspace")
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello-local"


async def test_a_failing_command_raises_command_exit_exception(
    sbx: LocalDockerSandbox,
) -> None:
    from e2b import CommandExitException

    with pytest.raises(CommandExitException) as caught:
        await sbx.commands.run("echo oops >&2; echo out; exit 7")
    assert caught.value.exit_code == 7
    assert "out" in caught.value.stdout
    assert "oops" in caught.value.stderr


async def test_a_timed_out_command_raises_timeout_exception(
    sbx: LocalDockerSandbox,
) -> None:
    from e2b import TimeoutException

    # The child must die together with the shell for exec to ever return, so
    # this doubles as proof that the process-group kill works against real PIDs.
    with pytest.raises(TimeoutException):
        await sbx.commands.run("sleep 30; echo never", timeout=1)


async def test_stream_callbacks_fire(sbx: LocalDockerSandbox) -> None:
    chunks: list[str] = []
    await sbx.commands.run("printf abc", on_stdout=chunks.append)
    assert "".join(chunks) == "abc"


async def test_envs_and_user_reach_the_command(sbx: LocalDockerSandbox) -> None:
    # `id -un` instead of $USER: slim images ship no USER env var, and docker
    # exec doesn't inject one — e2b's envd does. Identity still applies.
    result = await sbx.commands.run(
        'echo "$LSBX_VAR-$(id -un)"',
        envs={"LSBX_VAR": "v1"},
        user="root",
    )
    assert result.stdout.strip() == "v1-root"


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------


async def test_files_write_then_read_round_trip_text(
    sbx: LocalDockerSandbox,
) -> None:
    path = "/workspace/.gaia-lsbx-test/hello.txt"
    info = await sbx.files.write(path, "héllo gaia\n")
    assert info.name == "hello.txt"
    assert info.path == path
    assert await sbx.files.read(path) == "héllo gaia\n"


async def test_files_write_then_read_round_trip_binary(
    sbx: LocalDockerSandbox,
) -> None:
    payload = bytes(range(256)) * 4
    path = "/workspace/lsbx-bin/blob.bin"
    await sbx.files.write(path, payload)
    assert await sbx.files.read(path, format="bytes") == payload


async def test_files_read_missing_path_raises_not_found(
    sbx: LocalDockerSandbox,
) -> None:
    from e2b import NotFoundException

    with pytest.raises(NotFoundException):
        await sbx.files.read("/workspace/definitely-not-here.txt")


async def test_files_rename_returns_new_entry_info(sbx: LocalDockerSandbox) -> None:
    from e2b import NotFoundException

    src = "/workspace/lsbx-rename/first.txt"
    dst = "/workspace/lsbx-rename/second.txt"
    await sbx.files.make_dir("/workspace/lsbx-rename")
    await sbx.files.write(src, "move me")
    info = await sbx.files.rename(src, dst)
    assert info.path == dst
    assert info.name == "second.txt"
    assert info.size == len("move me")
    assert await sbx.files.read(dst) == "move me"
    with pytest.raises(NotFoundException):
        await sbx.files.get_info(src)


async def test_files_make_dir_and_get_info_dir(sbx: LocalDockerSandbox) -> None:
    from e2b.sandbox.filesystem.filesystem import FileType

    target = "/workspace/lsbx-mkdir/nested/deep"
    assert await sbx.files.make_dir(target) is True
    info = await sbx.files.get_info(target)
    assert info.type is FileType.DIR


async def test_files_remove_is_idempotent(sbx: LocalDockerSandbox) -> None:
    path = "/workspace/lsbx-rm/gone.txt"
    await sbx.files.write(path, "bye")
    await sbx.files.remove(path)
    # Documented divergence from e2b: removing an absent path succeeds.
    await sbx.files.remove(path)
    from e2b import NotFoundException

    with pytest.raises(NotFoundException):
        await sbx.files.read(path)


async def test_files_write_overwrites_in_place(sbx: LocalDockerSandbox) -> None:
    path = "/workspace/lsbx-ow/file.txt"
    await sbx.files.write(path, "first")
    await sbx.files.write(path, "second-longer-content")
    assert await sbx.files.read(path) == "second-longer-content"


# --------------------------------------------------------------------------
# container lifecycle
# --------------------------------------------------------------------------


async def test_ensure_started_is_idempotent(sbx: LocalDockerSandbox) -> None:
    await sbx.ensure_started()
    assert await sbx.is_running() is True


async def test_kill_removes_the_container() -> None:
    sandbox = LocalDockerSandbox(_uid())
    await sandbox.ensure_started()
    name = sandbox.container_name
    assert await sandbox.kill() is True
    assert await sandbox.is_running() is False
    state = await sandbox._container_state()
    assert state.exists is False
    del name  # kept the variable local for easier debugging of failures


async def test_kill_is_false_for_a_container_that_never_existed() -> None:
    sandbox = LocalDockerSandbox(_uid())
    assert await sandbox.kill() is False


async def test_beta_pause_stops_and_ensure_started_resumes_fs_intact() -> None:
    sandbox = LocalDockerSandbox(_uid())
    try:
        await sandbox.ensure_started()
        await sandbox.files.write("/workspace/pause-proof/canary.txt", "still here")
        await sandbox.beta_pause()
        assert await sandbox.is_running() is False
        await sandbox.ensure_started()
        # The workspace volume outlives the stop/start cycle.
        assert await sandbox.files.read("/workspace/pause-proof/canary.txt") == "still here"
    finally:
        await sandbox.kill()


async def test_a_broken_daemon_reads_as_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing docker binary must probe as dead, not raise mid-health-check."""

    async def broken_spawn(argv: list[str], *, stdin: bytes | None = None) -> Any:
        class _Proc:
            pid = 0
            returncode = 1

            async def communicate(self, _stdin: bytes | None = None) -> tuple[bytes, bytes]:
                msg = b"Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
                return b"", msg

        return _Proc()

    monkeypatch.setattr("app.services.sandbox.local_sandbox._spawn_process", broken_spawn)
    sandbox = LocalDockerSandbox(_uid())
    assert await sandbox.is_running() is False


# --------------------------------------------------------------------------
# the real user path: acquire_sandbox routing → real container
# --------------------------------------------------------------------------


async def test_acquire_sandbox_routes_selfhost_no_key_to_a_real_container() -> None:
    """End-to-end: tool-style usage through the public entry point."""
    from unittest.mock import patch

    from e2b import CommandExitException

    from app.services.sandbox.lifecycle import acquire_sandbox
    from app.services.sandbox.local_sandbox import (
        LocalDockerSandbox,
        pop_local_sandbox,
    )

    uid = _uid()
    try:
        with (
            patch.object(settings, "ENV", "selfhost"),
            patch.object(settings, "E2B_API_KEY", None),
        ):
            async with acquire_sandbox(uid) as sbx:
                assert isinstance(sbx, LocalDockerSandbox)
                result = await sbx.commands.run(
                    "echo routed && python3 -c 'print(1+1)'", cwd="/workspace"
                )
                assert result.exit_code == 0
                assert "routed" in result.stdout
                assert "2" in result.stdout
                # File tools across the same boundary.
                await sbx.files.write("/workspace/.gaia/drive-canary.txt", "alive")
                assert await sbx.files.read("/workspace/.gaia/drive-canary.txt") == "alive"
                with pytest.raises(CommandExitException) as caught:
                    await sbx.commands.run("exit 3")
                assert caught.value.exit_code == 3
            # Second acquire reuses the same container; workspace persists.
            async with acquire_sandbox(uid) as sbx:
                r = await sbx.commands.run("cat /workspace/.gaia/drive-canary.txt")
                assert r.stdout == "alive"
            await sbx.kill()
    finally:
        pop_local_sandbox(uid)
