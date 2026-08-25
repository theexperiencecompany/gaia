"""Unit tests for the local Docker-exec sandbox (hermetic — no daemon).

Every test drives `LocalDockerSandbox` through its real code paths with only
the subprocess seam (`local_sandbox._spawn_process`) replaced by fakes, so the
argv construction, e2b exception mapping, streaming callbacks and tar packing
are all exercised for real. The live-daemon counterparts live in
`test_local_sandbox_docker.py`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import io
import tarfile
from typing import Any

from e2b import CommandExitException, TimeoutException
from e2b.sandbox.filesystem.filesystem import FileType
import pytest

from app.services.sandbox import local_sandbox
from app.services.sandbox.local_sandbox import (
    LocalDockerSandbox,
    LocalSandboxError,
    container_name_for,
    get_local_sandbox,
    pop_local_sandbox,
)

# --------------------------------------------------------------------------
# fake subprocess layer
# --------------------------------------------------------------------------


class FakeProcess:
    """Minimal stand-in for asyncio.subprocess.Process as used by the module."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
        wait_delay: float = 0.0,
    ) -> None:
        self._stdout_bytes = stdout
        self._stderr_bytes = stderr
        self._hang = hang
        self.pid = 4242
        self.returncode: int | None = None
        self._returncode = returncode
        self._wait_delay = wait_delay
        self.communicated_input: bytes | None = None
        self.killed = False
        # Readers are built lazily: constructing an asyncio.StreamReader
        # requires a running event loop, and these are first touched inside
        # the coroutine under test.
        self._stdout: asyncio.StreamReader | None = None
        self._stderr: asyncio.StreamReader | None = None

    @staticmethod
    def _reader(data: bytes) -> asyncio.StreamReader:
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        return reader

    @property
    def stdout(self) -> asyncio.StreamReader:
        if self._stdout is None:
            self._stdout = (
                asyncio.StreamReader()
                if (self._hang or self.killed)
                else (self._reader(self._stdout_bytes))
            )
            if self.killed:
                self._stdout.feed_eof()
        return self._stdout

    @property
    def stderr(self) -> asyncio.StreamReader:
        if self._stderr is None:
            self._stderr = (
                asyncio.StreamReader()
                if (self._hang or self.killed)
                else (self._reader(self._stderr_bytes))
            )
            if self.killed:
                self._stderr.feed_eof()
        return self._stderr

    def kill(self) -> None:
        self.killed = True
        # A SIGKILLed process's pipes close — unblock any pending readers.
        for reader in (self._stdout, self._stderr):
            if reader is not None:
                reader.feed_eof()

    async def communicate(self, stdin: bytes | None = None) -> tuple[bytes, bytes]:
        self.communicated_input = stdin
        self.returncode = self._returncode
        out = await self.stdout.read(-1)
        err = await self.stderr.read(-1)
        return out, err

    async def wait(self) -> int:
        if self._wait_delay:
            await asyncio.sleep(self._wait_delay)
        if self.returncode is None:
            self.returncode = -9 if self.killed else self._returncode
        return self.returncode


class SpawnRecorder:
    """Patch target for `_spawn_process`: records argvs, hands back responses."""

    def __init__(self, *responses: FakeProcess | Exception) -> None:
        self.argvs: list[list[str]] = []
        stdins: list[bytes | None] = []
        self.stdins = stdins
        self._responses = list(responses)

    async def __call__(self, argv: list[str], *, stdin: bytes | None = None) -> Any:
        self.argvs.append(argv)
        self.stdins.append(stdin)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def argv(self, index: int = 0) -> list[str]:
        return self.argvs[index]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> SpawnRecorder:
    """Default recorder: every spawn succeeds silently unless told otherwise."""
    rec = SpawnRecorder(FakeProcess())
    monkeypatch.setattr(local_sandbox, "_spawn_process", rec)
    return rec


def _sandbox(user_id: str = "u1") -> LocalDockerSandbox:
    return LocalDockerSandbox(user_id)


# --------------------------------------------------------------------------
# container naming
# --------------------------------------------------------------------------


def test_a_plain_user_id_maps_to_a_prefixed_container_name() -> None:
    assert container_name_for("u1") == "gaia-sandbox-u1"


def test_unsafe_user_id_chars_are_sanitized_with_a_collision_guard() -> None:
    name = container_name_for("user/with spaces")
    assert name.startswith("gaia-sandbox-user-with-spaces-")
    # Deterministic, and distinct from a hypothetical clean user that would
    # sanitize to the same prefix.
    assert name == container_name_for("user/with spaces")


def test_distinct_users_never_share_a_sanitized_name() -> None:
    # "a/b" sanitizes to "a-b"; the digest suffix must keep it from colliding
    # with the literal user "a-b".
    assert container_name_for("a/b") != container_name_for("a-b")


def test_sandbox_id_is_the_container_name() -> None:
    sbx = _sandbox()
    assert sbx.sandbox_id == sbx.container_name == "gaia-sandbox-u1"


def test_empty_user_id_is_rejected_eagerly() -> None:
    with pytest.raises(ValueError, match="user_id"):
        LocalDockerSandbox("")


# --------------------------------------------------------------------------
# commands.run
# --------------------------------------------------------------------------


async def test_run_executes_through_a_login_shell_and_returns_the_result(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stdout=b"hello\n", stderr=b"", returncode=0)]
    result = await _sandbox().commands.run("echo hello")
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert recorder.argv() == [
        "docker",
        "exec",
        "gaia-sandbox-u1",
        "/bin/bash",
        "-l",
        "-c",
        "echo hello",
    ]


async def test_run_forwards_user_envs_and_cwd_as_exec_flags(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(returncode=0)]
    await _sandbox().commands.run("whoami", user="root", envs={"A": "b"}, cwd="/workspace/s")
    argv = recorder.argv()
    assert "--user" in argv and argv[argv.index("--user") + 1] == "root"
    assert "--env" in argv and argv[argv.index("--env") + 1] == "A=b"
    assert "--workdir" in argv and argv[argv.index("--workdir") + 1] == "/workspace/s"


async def test_a_non_zero_exit_raises_command_exit_exception_with_captured_output(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stdout=b"partial out", stderr=b"boom", returncode=3)]
    with pytest.raises(CommandExitException) as caught:
        await _sandbox().commands.run("false")
    # Must be e2b's own type — the tools catch `e2b.CommandExitException`.
    assert type(caught.value) is CommandExitException
    assert caught.value.exit_code == 3
    assert caught.value.stdout == "partial out"
    assert caught.value.stderr == "boom"


async def test_stream_callbacks_receive_decoded_output_chunks(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stdout=b"out!", stderr=b"err!", returncode=0)]
    seen: dict[str, list[str]] = {"o": [], "e": []}
    await _sandbox().commands.run("echo", on_stdout=seen["o"].append, on_stderr=seen["e"].append)
    assert "".join(seen["o"]) == "out!"
    assert "".join(seen["e"]) == "err!"


async def test_a_timed_out_command_kills_its_process_group_and_raises_timeout(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = FakeProcess(hang=True, wait_delay=0.0)
    killed_pids: list[int] = []

    def fake_kill(pid: int) -> None:
        killed_pids.append(pid)
        proc.kill()

    monkeypatch.setattr(local_sandbox, "_kill_process_group", fake_kill)
    recorder._responses = [proc]
    started = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutException):
        await _sandbox().commands.run("sleep forever", timeout=0.05)
    elapsed = asyncio.get_running_loop().time() - started
    assert killed_pids == [4242], "the whole process group must be SIGKILLed"
    assert proc.killed
    assert elapsed < 2, "timeout must fire at the deadline, not wait on pipes"


async def test_zero_timeout_disables_the_deadline(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"done", returncode=0)]
    result = await _sandbox().commands.run("slow but finite", timeout=0)
    assert result.stdout == "done"


async def test_background_true_is_rejected_loudly_not_faked(
    recorder: SpawnRecorder,
) -> None:
    with pytest.raises(NotImplementedError, match="background"):
        await _sandbox().commands.run("x", background=True)
    assert recorder.argvs == []


# --------------------------------------------------------------------------
# files.write / read
# --------------------------------------------------------------------------


async def test_write_creates_parents_then_copies_an_in_memory_tar(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(), FakeProcess()]
    info = await _sandbox().files.write("/workspace/.gaia/canary.txt", "ts-1")

    mkdir_argv, cp_argv = recorder.argv(0), recorder.argv(1)
    assert mkdir_argv[mkdir_argv.index("mkdir") :] == ["mkdir", "-p", "--", "/workspace/.gaia"]
    assert cp_argv[:3] == ["docker", "cp", "-"]
    assert cp_argv[3] == "gaia-sandbox-u1:/workspace/.gaia"
    tar_payload = recorder.stdins[1]
    assert tar_payload is not None
    with tarfile.open(fileobj=io.BytesIO(tar_payload)) as tar:
        members = tar.getmembers()
        assert len(members) == 1
        assert members[0].name == "canary.txt"
        assert tar.extractfile(members[0]).read() == b"ts-1"  # type: ignore[union-attr]  # tarfile stubs: extractfile is Optional only for sparse/odd members
    assert info.name == "canary.txt"
    assert info.type is FileType.FILE
    assert info.path == "/workspace/.gaia/canary.txt"


async def test_write_round_trips_arbitrary_bytes_without_shell_mangling(
    recorder: SpawnRecorder,
) -> None:
    payload = bytes(range(256))
    recorder._responses = [FakeProcess(), FakeProcess()]
    await _sandbox().files.write("/workspace/blob.bin", payload)
    tar_payload = recorder.stdins[1]
    assert tar_payload is not None
    with tarfile.open(fileobj=io.BytesIO(tar_payload)) as tar:
        member = tar.getmembers()[0]
        assert member.name == "blob.bin"
        assert tar.extractfile(member).read() == payload  # type: ignore[union-attr]  # tarfile stubs: extractfile is Optional only for sparse/odd members


async def test_write_rejects_non_str_bytes_data_instead_of_corrupting_it(
    recorder: SpawnRecorder,
) -> None:
    with pytest.raises(TypeError, match="str or bytes"):
        await _sandbox().files.write("/workspace/x", 123)  # type: ignore[arg-type]  # deliberately wrong type: the runtime guard under test must reject it
    assert recorder.argvs == []


async def test_write_rejects_relative_paths(recorder: SpawnRecorder) -> None:
    with pytest.raises(ValueError, match="absolute"):
        await _sandbox().files.write("relative.txt", "x")
    assert recorder.argvs == []


async def test_read_text_returns_decoded_contents(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout="héllo\n".encode(), returncode=0)]
    assert await _sandbox().files.read("/workspace/f.txt") == "héllo\n"
    assert recorder.argv()[recorder.argv().index("cat") :] == ["cat", "--", "/workspace/f.txt"]


async def test_read_bytes_returns_raw_bytes(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"\x00\x01\x02", returncode=0)]
    assert await _sandbox().files.read("/workspace/f.bin", format="bytes") == b"\x00\x01\x02"


async def test_read_of_a_missing_file_raises_e2b_not_found(
    recorder: SpawnRecorder,
) -> None:
    from e2b import NotFoundException

    recorder._responses = [
        FakeProcess(stderr=b"cat: /nope: No such file or directory", returncode=1)
    ]
    with pytest.raises(NotFoundException):
        await _sandbox().files.read("/workspace/nope")


async def test_read_failure_that_is_not_missing_is_loud(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stderr=b"cat: permission denied", returncode=1)]
    with pytest.raises(LocalSandboxError, match="permission denied"):
        await _sandbox().files.read("/workspace/secret")


async def test_read_stream_format_is_unsupported(recorder: SpawnRecorder) -> None:
    with pytest.raises(ValueError, match="format"):
        await _sandbox().files.read("/workspace/f", format="stream")
    assert recorder.argvs == []


# --------------------------------------------------------------------------
# files.rename / remove / make_dir / get_info
# --------------------------------------------------------------------------


def _stat_line(kind: str = "regular file") -> bytes:
    return b"123|81a4|644|root|root|1700000000|" + kind.encode()


async def test_rename_moves_then_returns_metadata_for_the_new_path(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(), FakeProcess(stdout=_stat_line())]
    info = await _sandbox().files.rename("/tmp/a.gaia-tmp", "/workspace/a.txt")
    mv_argv = recorder.argv(0)
    assert mv_argv[mv_argv.index("mv") :] == ["mv", "--", "/tmp/a.gaia-tmp", "/workspace/a.txt"]
    assert info.path == "/workspace/a.txt"
    assert info.size == 123


async def test_remove_is_rm_rf(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess()]
    assert await _sandbox().files.remove("/workspace/tmp") is None
    argv = recorder.argv()
    assert argv[argv.index("rm") :] == ["rm", "-rf", "--", "/workspace/tmp"]


async def test_make_dir_creates_parents_and_returns_true(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess()]
    assert await _sandbox().files.make_dir("/workspace/s/scratch") is True
    argv = recorder.argv()
    assert argv[argv.index("mkdir") :] == ["mkdir", "-p", "--", "/workspace/s/scratch"]


async def test_get_info_parses_stat_into_an_e2b_entry_info(
    recorder: SpawnRecorder,
) -> None:
    from datetime import UTC

    recorder._responses = [FakeProcess(stdout=_stat_line())]
    info = await _sandbox().files.get_info("/workspace/a.txt")
    assert info.type is FileType.FILE
    assert info.size == 123
    # %f is the hex mode incl. file-type bits: 0x81a4 == 0o100644.
    assert info.mode == 0o100644
    assert info.permissions == "644"
    assert info.owner == "root"
    assert info.group == "root"
    # e2b's protobuf datetimes are naive UTC — atomic_write re-tags UTC.
    expected = datetime.fromtimestamp(1700000000, tz=UTC).replace(tzinfo=None)
    assert info.modified_time == expected
    assert info.modified_time.tzinfo is None


async def test_get_info_classifies_directories(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=_stat_line("directory"))]
    info = await _sandbox().files.get_info("/workspace")
    assert info.type is FileType.DIR


async def test_get_info_on_a_missing_path_raises_not_found(
    recorder: SpawnRecorder,
) -> None:
    from e2b import NotFoundException

    recorder._responses = [
        FakeProcess(stderr=b"stat: cannot statx: No such file or directory", returncode=1)
    ]
    with pytest.raises(NotFoundException):
        await _sandbox().files.get_info("/workspace/nope")


async def test_garbled_stat_output_is_a_loud_error_not_default_fields(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stdout=b"garbage", returncode=0)]
    with pytest.raises(LocalSandboxError, match="stat output"):
        await _sandbox().files.get_info("/workspace/x")


# --------------------------------------------------------------------------
# container lifecycle
# --------------------------------------------------------------------------


def _inspect_response(running: str, rc: int = 0) -> FakeProcess:
    return FakeProcess(
        stdout=running.encode(), stderr=b"" if rc == 0 else b"No such object\n", returncode=rc
    )


async def test_ensure_started_short_circuits_when_already_running(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [_inspect_response("true")]
    await _sandbox().ensure_started()
    assert len(recorder.argvs) == 1
    assert "inspect" in " ".join(recorder.argv())


async def test_ensure_started_starts_an_existing_stopped_container(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [
        _inspect_response("false"),
        FakeProcess(returncode=0),
        _inspect_response("true"),
    ]
    await _sandbox().ensure_started()
    assert recorder.argv(1)[:2] == ["docker", "start"]


async def test_ensure_started_creates_a_missing_container_on_the_shared_volume(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(returncode=0),
        _inspect_response("true"),
    ]
    await _sandbox().ensure_started()
    run = recorder.argv(1)
    assert run[:2] == ["docker", "run"]
    assert run[run.index("--name") + 1] == "gaia-sandbox-u1"
    assert run[run.index("--volume") + 1] == "gaia-sandbox-workspace:/workspace"
    assert run[-3:] == ["python:3.12-slim", "sleep", "infinity"]


async def test_ensure_started_surfaces_a_failed_create(recorder: SpawnRecorder) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(stderr=b"daemon unreachable", returncode=125),
    ]
    with pytest.raises(LocalSandboxError, match="daemon unreachable"):
        await _sandbox().ensure_started()


async def test_ensure_started_fails_if_the_container_never_runs(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(returncode=0),
        FakeProcess(stderr=b"No such object", returncode=1),
    ]
    with pytest.raises(LocalSandboxError, match="running"):
        await _sandbox().ensure_started()


async def test_is_running_reflects_inspect(recorder: SpawnRecorder) -> None:
    recorder._responses = [_inspect_response("true")]
    assert await _sandbox().is_running(request_timeout=4) is True
    recorder._responses = [_inspect_response("false")]
    assert await _sandbox().is_running() is False


async def test_is_running_reports_false_for_a_missing_container(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stderr=b"Error: No such object", returncode=1)]
    assert await _sandbox().is_running() is False


async def test_is_running_treats_daemon_failures_as_dead_not_crash(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stderr=b"cannot connect to daemon", returncode=1)]
    assert await _sandbox().is_running() is False


async def test_set_timeout_validates_but_does_nothing(recorder: SpawnRecorder) -> None:
    await _sandbox().set_timeout(3600)
    assert recorder.argvs == []
    with pytest.raises(ValueError, match="positive"):
        await _sandbox().set_timeout(0)


async def test_beta_pause_stops_the_container(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess()]
    await _sandbox().beta_pause()
    assert recorder.argv()[:2] == ["docker", "stop"]


async def test_beta_pause_surfaces_failures(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stderr=b"nope", returncode=1)]
    with pytest.raises(LocalSandboxError, match="stop failed"):
        await _sandbox().beta_pause()


async def test_kill_reports_true_when_removed(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(returncode=0)]
    assert await _sandbox().kill() is True


async def test_kill_is_false_for_a_missing_container_on_old_daemons(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"Error response from daemon: No such container: x", returncode=1)
    ]
    assert await _sandbox().kill() is False


async def test_kill_spots_a_zero_exit_that_actually_removed_nothing(
    recorder: SpawnRecorder,
) -> None:
    # Docker 29 exits 0 while printing "No such container" for a forced remove
    # of a missing container — stderr must win over the exit code, or every
    # double-kill would claim success.
    recorder._responses = [
        FakeProcess(stderr=b"Error response from daemon: No such container: x", returncode=0)
    ]
    assert await _sandbox().kill() is False


async def test_kill_surfaces_genuine_daemon_failures(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stderr=b"daemon unreachable", returncode=125)]
    with pytest.raises(LocalSandboxError, match="rm failed"):
        await _sandbox().kill()


# --------------------------------------------------------------------------
# per-process registry
# --------------------------------------------------------------------------


def test_registry_hands_back_the_same_instance_per_user() -> None:
    try:
        first = get_local_sandbox("reg-user")
        assert get_local_sandbox("reg-user") is first
        assert get_local_sandbox("other-user") is not first
    finally:
        pop_local_sandbox("reg-user")
        pop_local_sandbox("other-user")
    assert pop_local_sandbox("reg-user") is None
