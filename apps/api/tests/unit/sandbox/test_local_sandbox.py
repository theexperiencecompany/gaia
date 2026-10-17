"""Unit tests for the local Docker-exec sandbox (hermetic, no daemon).

Every test drives LocalDockerSandbox through its real code paths with only
the subprocess spawn seam replaced by fakes, so argv construction, exception
mapping, streaming callbacks and tar packing are all exercised for real.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import io
import itertools
import os
from pathlib import Path
import re
import tarfile
from typing import Any

from e2b import CommandExitException, NotFoundException, TimeoutException
from e2b.sandbox.filesystem.filesystem import FileType
import pytest
from tests.helpers import captured_wide_event

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.sandbox import SELFHOST_WORKSPACE_VOLUME
from app.services.sandbox import local_sandbox
from app.services.sandbox.local_sandbox import (
    LocalDockerSandbox,
    LocalSandboxError,
    container_name_for,
    get_local_sandbox,
    pop_local_sandbox,
)
from app.services.storage.juicefs import JuiceFSUnavailable

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
    """Spawn-process double: records argvs, hands back queued responses."""

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
        "timeout",
        "--signal=KILL",
        "60s",
        "/bin/bash",
        "-l",
        "-c",
        "echo hello",
    ]


async def test_run_forwards_user_envs_and_cwd_as_exec_flags(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(returncode=0)]
    await _sandbox().commands.run(
        "whoami", user="root", envs={"A": "b", "C": "d"}, cwd="/workspace/s"
    )
    assert recorder.argv()[: recorder.argv().index("timeout")] == [
        "docker",
        "exec",
        "--user",
        "root",
        "--env",
        "A=b",
        "--env",
        "C=d",
        "--workdir",
        "/workspace/s",
        "gaia-sandbox-u1",
    ]


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


async def test_the_timeout_is_enforced_inside_the_container_where_it_kills_the_command(
    recorder: SpawnRecorder,
) -> None:
    # Killing the host `docker exec` client leaves the command running in the
    # container; coreutils timeout in the container kills its process group.
    recorder._responses = [FakeProcess(returncode=0)]
    await _sandbox().commands.run("make build", timeout=300)
    argv = recorder.argv()
    assert argv[argv.index("gaia-sandbox-u1") + 1 :] == [
        "timeout",
        "--signal=KILL",
        "300s",
        "/bin/bash",
        "-l",
        "-c",
        "make build",
    ]


async def test_a_command_the_in_container_timeout_killed_raises_timeout(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(returncode=137, wait_delay=0.06)]
    with pytest.raises(TimeoutException, match="timeout"):
        await _sandbox().commands.run("sleep forever", timeout=0.05)


async def test_a_sigkill_before_the_deadline_is_an_exit_not_a_timeout(
    recorder: SpawnRecorder,
) -> None:
    # e.g. the kernel OOM killer: the command died, but not of our deadline.
    recorder._responses = [FakeProcess(stderr=b"Killed", returncode=137)]
    with pytest.raises(CommandExitException) as caught:
        await _sandbox().commands.run("python hog.py", timeout=60)
    assert caught.value.exit_code == 137


async def test_an_unresponsive_exec_client_is_killed_after_the_grace_period(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = FakeProcess(hang=True, wait_delay=0.0)
    killed_pids: list[int] = []

    def fake_kill(pid: int) -> None:
        killed_pids.append(pid)
        proc.kill()

    monkeypatch.setattr(local_sandbox, "_kill_process_group", fake_kill)
    monkeypatch.setattr(local_sandbox, "LOCAL_SANDBOX_EXEC_TIMEOUT_GRACE_SECONDS", 0.05)
    recorder._responses = [proc]
    started = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutException):
        await _sandbox().commands.run("sleep forever", timeout=0.05)
    elapsed = asyncio.get_running_loop().time() - started
    assert killed_pids == [4242], "the exec client's process group must be SIGKILLed"
    assert proc.killed
    assert elapsed < 2, "the host backstop must fire, not wait on pipes"


async def test_zero_timeout_disables_the_deadline(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"done", returncode=0)]
    result = await _sandbox().commands.run("slow but finite", timeout=0)
    assert result.stdout == "done"
    assert "timeout" not in recorder.argv()


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
    cp_process = FakeProcess()
    recorder._responses = [FakeProcess(), cp_process]
    info = await _sandbox().files.write("/workspace/.gaia/canary.txt", "ts-1")

    mkdir_argv, cp_argv = recorder.argv(0), recorder.argv(1)
    assert mkdir_argv[mkdir_argv.index("mkdir") :] == ["mkdir", "-p", "--", "/workspace/.gaia"]
    assert cp_argv[:4] == ["docker", "cp", "--archive", "-"]
    assert cp_argv[4] == "gaia-sandbox-u1:/workspace/.gaia"
    tar_payload = recorder.stdins[1]
    assert tar_payload is not None
    assert cp_process.communicated_input == tar_payload
    with tarfile.open(fileobj=io.BytesIO(tar_payload)) as tar:
        members = tar.getmembers()
        assert len(members) == 1
        assert members[0].name == "canary.txt"
        # --archive keeps these, so the file belongs to the sandbox user, not root.
        assert (members[0].uid, members[0].gid) == (os.getuid(), os.getgid())
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


_CURRENT_LAYOUT = f"true {local_sandbox.LOCAL_SANDBOX_LAYOUT}"


def _inspect_response(state: str = _CURRENT_LAYOUT, rc: int = 0) -> FakeProcess:
    return FakeProcess(
        stdout=state.encode(), stderr=b"" if rc == 0 else b"No such object\n", returncode=rc
    )


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the API at a tmpdir workspace; a tmpdir is not a real mountpoint."""
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(tmp_path))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    return tmp_path


def _mount_specs(run: list[str]) -> list[dict[str, str]]:
    specs = []
    for flag, value in itertools.pairwise(run):
        if flag == "--mount":
            specs.append(dict(part.partition("=")[::2] for part in value.split(",")))
    return specs


async def _create(recorder: SpawnRecorder, user_id: str) -> list[str]:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(returncode=0),
        FakeProcess(returncode=0),
        _inspect_response(),
    ]
    await _sandbox(user_id).ensure_started()
    return next(argv for argv in recorder.argvs if argv[:2] == ["docker", "run"])


async def test_ensure_started_short_circuits_when_already_running(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [_inspect_response()]
    await _sandbox().ensure_started()
    assert len(recorder.argvs) == 1
    assert "inspect" in " ".join(recorder.argv())


async def test_ensure_started_starts_an_existing_stopped_container(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [
        _inspect_response(f"false {local_sandbox.LOCAL_SANDBOX_LAYOUT}"),
        FakeProcess(returncode=0),
        _inspect_response(),
    ]
    await _sandbox().ensure_started()
    assert recorder.argv(1)[:2] == ["docker", "start"]


async def test_a_users_sandbox_mounts_only_that_users_subtree(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    (workspace_root / "users" / "userA").mkdir(parents=True)
    (workspace_root / "users" / "userA" / "secret.txt").write_text("A's data")

    run = await _create(recorder, "userB")

    assert "--volume" not in run and "-v" not in run
    specs = _mount_specs(run)
    assert {spec["dst"]: spec["volume-subpath"] for spec in specs} == {
        "/workspace": "users/userB",
        "/workspace/skills": "skills/userB",
        "/workspace/.system": "_system",
    }
    assert all(spec["src"] == SELFHOST_WORKSPACE_VOLUME for spec in specs)
    assert [spec["dst"] for spec in specs if "readonly" in spec] == [
        "/workspace/skills",
        "/workspace/.system",
    ]
    assert not any("userA" in arg for arg in run)


async def test_the_mounted_subpaths_exist_before_docker_run(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    # The daemon refuses a volume-subpath that does not exist yet.
    await _create(recorder, "userB")

    for rel in (
        "users/userB",
        "users/userB/skills",
        "users/userB/.system",
        "skills/userB",
        "_system",
    ):
        assert (workspace_root / rel).is_dir(), rel


async def test_the_sandbox_runs_as_the_api_user_so_both_can_write_the_workspace(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    run = await _create(recorder, "userB")

    assert run[run.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert run[run.index("--label") + 1] == "gaia.sandbox.user=userB"
    assert f"{local_sandbox.LOCAL_SANDBOX_LAYOUT_LABEL}={local_sandbox.LOCAL_SANDBOX_LAYOUT}" in run
    assert run[-3:] == ["python:3.12-slim", "sleep", "infinity"]


def _flag(run: list[str], flag: str) -> str:
    return run[run.index(flag) + 1]


async def test_the_sandbox_is_capped_so_one_user_cannot_starve_the_host(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    run = await _create(recorder, "userB")

    assert _flag(run, "--memory") == "2g"
    assert _flag(run, "--memory-swap") == "2g", "swap equal to memory means no swap"
    assert _flag(run, "--pids-limit") == "512"
    assert _flag(run, "--cpus") == "2"
    assert _flag(run, "--cap-drop") == "ALL"
    assert _flag(run, "--security-opt") == "no-new-privileges"


async def test_the_sandbox_joins_an_isolated_network_not_the_datastores_network(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    run = await _create(recorder, "userB")

    assert _flag(run, "--network") == "gaia-sandbox"
    network_create = next(argv for argv in recorder.argvs if argv[1:3] == ["network", "create"])
    assert network_create[-1] == "gaia-sandbox"
    assert _flag(network_create, "--driver") == "bridge"
    assert _flag(network_create, "--opt") == "com.docker.network.bridge.enable_icc=false"
    assert recorder.argvs.index(network_create) < recorder.argvs.index(run)


async def test_an_existing_sandbox_network_is_reused(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(stderr=b"Error: network with name gaia-sandbox already exists", returncode=1),
        FakeProcess(returncode=0),
        _inspect_response(),
    ]
    await _sandbox("userB").ensure_started()
    assert recorder.argv(2)[:2] == ["docker", "run"]


async def test_a_failed_network_create_stops_the_sandbox_from_starting(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(stderr=b"permission denied", returncode=1),
    ]
    with pytest.raises(LocalSandboxError, match="permission denied"):
        await _sandbox("userB").ensure_started()
    assert not any(argv[:2] == ["docker", "run"] for argv in recorder.argvs)


async def test_a_container_from_before_the_limits_is_replaced_not_restarted(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    recorder._responses = [
        _inspect_response("true per-user-subpath-v1"),
        FakeProcess(returncode=0),
        FakeProcess(returncode=0),
        FakeProcess(returncode=0),
        _inspect_response(),
    ]
    await _sandbox("userB").ensure_started()
    assert recorder.argv(1)[:3] == ["docker", "rm", "-f"]
    assert not any(argv[:2] == ["docker", "start"] for argv in recorder.argvs)


async def test_a_container_from_the_shared_volume_era_is_replaced_not_restarted(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    recorder._responses = [
        _inspect_response("true "),
        FakeProcess(returncode=0),
        FakeProcess(returncode=0),
        FakeProcess(returncode=0),
        _inspect_response(),
    ]
    await _sandbox("userB").ensure_started()

    assert recorder.argv(1)[:3] == ["docker", "rm", "-f"]
    assert recorder.argv(3)[:2] == ["docker", "run"]
    assert not any(argv[:2] == ["docker", "start"] for argv in recorder.argvs)


@pytest.mark.parametrize("user_id", ["a,volume-subpath=..", "../userA", "a b"])
async def test_a_user_id_that_could_rewrite_the_mount_spec_never_reaches_docker_run(
    recorder: SpawnRecorder, workspace_root: Path, user_id: str
) -> None:
    recorder._responses = [FakeProcess(stderr=b"No such object", returncode=1)]
    with pytest.raises(ValueError, match="unsafe user_id"):
        await _sandbox(user_id).ensure_started()
    assert not any(argv[:2] == ["docker", "run"] for argv in recorder.argvs)


async def test_no_sandbox_starts_without_the_workspace_volume(
    recorder: SpawnRecorder, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: False)
    recorder._responses = [FakeProcess(stderr=b"No such object", returncode=1)]
    with pytest.raises(JuiceFSUnavailable):
        await _sandbox("userB").ensure_started()
    assert not any(argv[:2] == ["docker", "run"] for argv in recorder.argvs)


async def test_ensure_started_surfaces_a_failed_create(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(returncode=0),
        FakeProcess(stderr=b"daemon unreachable", returncode=125),
    ]
    with pytest.raises(LocalSandboxError, match="daemon unreachable"):
        await _sandbox().ensure_started()


async def test_ensure_started_fails_if_the_container_never_runs(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(returncode=0),
        FakeProcess(returncode=0),
        FakeProcess(stderr=b"No such object", returncode=1),
    ]
    with pytest.raises(LocalSandboxError, match="running"):
        await _sandbox().ensure_started()


async def test_is_running_reflects_inspect(recorder: SpawnRecorder) -> None:
    recorder._responses = [_inspect_response()]
    assert await _sandbox().is_running(request_timeout=4) is True
    recorder._responses = [_inspect_response(f"false {local_sandbox.LOCAL_SANDBOX_LAYOUT}")]
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
    recorder._responses = [FakeProcess(stdout=b"gaia-sandbox-u1\n", returncode=0)]
    assert await _sandbox().kill() is True


async def test_kill_is_false_when_a_zero_exit_names_no_removed_container(
    recorder: SpawnRecorder,
) -> None:
    # Docker 29.8 exits 0 with empty output for a forced remove of a missing container.
    recorder._responses = [FakeProcess(returncode=0)]
    assert await _sandbox().kill() is False


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


# --------------------------------------------------------------------------
# exact contracts: names, argv, messages and lenient decoding
# --------------------------------------------------------------------------

_INVALID_UTF8 = b"bad \xff byte"
_REPLACED = "bad \ufffd byte"


def test_a_clean_user_id_keeps_its_case_and_dots() -> None:
    assert container_name_for("Xavier.Doe-1") == "gaia-sandbox-Xavier.Doe-1"


@pytest.mark.parametrize(
    ("user_id", "pattern"),
    [("-.ab.-", r"gaia-sandbox-ab-[0-9a-f]{8}"), ("///", r"gaia-sandbox-user-[0-9a-f]{8}")],
    ids=["edge-punctuation-stripped", "nothing-usable"],
)
def test_a_sanitized_name_carries_an_eight_hex_digest(user_id: str, pattern: str) -> None:
    assert re.fullmatch(pattern, container_name_for(user_id))


def test_an_empty_user_id_names_the_missing_field() -> None:
    with pytest.raises(ValueError) as raised:
        LocalDockerSandbox("")
    assert str(raised.value) == "user_id is required"


async def test_a_missing_file_names_the_operation_and_path(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stderr=b"cat: x: No such file or directory", returncode=1)]
    with pytest.raises(NotFoundException) as raised:
        await _sandbox().files.read("/workspace/nope")
    assert str(raised.value) == "files.read: /workspace/nope: no such file or directory"


async def test_undecodable_daemon_stderr_is_replaced_not_fatal(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stderr=_INVALID_UTF8, returncode=1)]
    with pytest.raises(LocalSandboxError) as raised:
        await _sandbox().files.read("/workspace/f")
    assert _REPLACED in str(raised.value)


async def test_undecodable_file_text_is_replaced_not_fatal(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=_INVALID_UTF8)]
    assert await _sandbox().files.read("/workspace/f") == _REPLACED


async def test_a_character_split_across_output_chunks_arrives_whole(
    recorder: SpawnRecorder,
) -> None:
    # The first read ends one byte into the two-byte "é".
    text = "a" * (local_sandbox._STREAM_CHUNK_BYTES - 1) + "é tail"
    recorder._responses = [FakeProcess(stdout=text.encode(), stderr=text.encode())]
    streamed: list[str] = []

    result = await _sandbox().commands.run("cat accents", on_stdout=streamed.append)

    assert result.stdout == text
    assert result.stderr == text
    assert "".join(streamed) == text


async def test_output_cut_mid_character_ends_with_a_replacement_not_silence(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stdout="done é".encode()[:-1])]
    streamed: list[str] = []
    result = await _sandbox().commands.run("killed mid-write", on_stdout=streamed.append)
    assert result.stdout == "done �"
    assert "".join(streamed) == "done �"


async def test_undecodable_command_output_is_replaced_and_every_chunk_is_kept(
    recorder: SpawnRecorder,
) -> None:
    big = b"a" * (local_sandbox._STREAM_CHUNK_BYTES + 10)
    recorder._responses = [FakeProcess(stdout=big, stderr=big + _INVALID_UTF8)]
    result = await _sandbox().commands.run("cat big")
    assert result.stdout == big.decode()
    assert result.stderr == big.decode() + _REPLACED


async def test_a_failed_inspect_names_the_container_and_the_daemon_error(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stderr=b"cannot connect to daemon\n", returncode=1)]
    with pytest.raises(LocalSandboxError) as raised:
        await _sandbox().ensure_started()
    assert (
        str(raised.value) == "docker inspect failed for gaia-sandbox-u1: cannot connect to daemon"
    )
    layout = local_sandbox.LOCAL_SANDBOX_LAYOUT_LABEL
    assert recorder.argv() == [
        "docker",
        "container",
        "inspect",
        "-f",
        f'{{{{.State.Running}}}} {{{{index .Config.Labels "{layout}"}}}}',
        "gaia-sandbox-u1",
    ]


async def test_a_running_container_without_a_layout_label_reports_running(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stdout=b"true \n")]
    assert await _sandbox().is_running() is True


async def test_undecodable_stat_output_is_replaced_not_fatal(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"1|81a4|644|r\xffot|root|1700000000|regular file")]
    info = await _sandbox().files.get_info("/workspace/a.txt")
    assert info.owner == "r\ufffdot"


async def test_undecodable_inspect_output_is_replaced_not_fatal(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"true \xff")]
    assert await _sandbox().is_running() is True


async def test_a_failed_liveness_probe_is_a_warning_on_the_wide_event(
    recorder: SpawnRecorder,
) -> None:
    recorder._responses = [FakeProcess(stderr=b"cannot connect to daemon", returncode=1)]
    async with captured_wide_event() as event:
        assert await _sandbox().is_running() is False
    assert event["warnings"] == [
        {
            "msg": f"{LogTag.SANDBOX} liveness probe failed; reporting dead",
            "container": "gaia-sandbox-u1",
            "error": "docker inspect failed for gaia-sandbox-u1: cannot connect to daemon",
        }
    ]


async def test_docker_run_names_labels_and_restarts_the_container(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    run = await _create(recorder, "userB")

    assert run[:5] == ["docker", "run", "-d", "--name", "gaia-sandbox-userB"]
    assert [value for flag, value in itertools.pairwise(run) if flag == "--label"] == [
        "gaia.sandbox.user=userB",
        f"{local_sandbox.LOCAL_SANDBOX_LAYOUT_LABEL}={local_sandbox.LOCAL_SANDBOX_LAYOUT}",
    ]
    assert _flag(run, "--env") == f"HOME={local_sandbox.LOCAL_SANDBOX_HOME}"
    assert _flag(run, "--restart") == "unless-stopped"


async def test_a_sandbox_whose_workspace_already_exists_is_created_again(
    recorder: SpawnRecorder, workspace_root: Path
) -> None:
    await _create(recorder, "userB")
    recorder.argvs.clear()

    run = await _create(recorder, "userB")

    assert run[:2] == ["docker", "run"]


async def test_a_stopped_container_is_started_by_name(recorder: SpawnRecorder) -> None:
    recorder._responses = [
        _inspect_response(f"false {local_sandbox.LOCAL_SANDBOX_LAYOUT}"),
        FakeProcess(returncode=0),
        _inspect_response(),
    ]
    await _sandbox().ensure_started()
    assert recorder.argv(1) == ["docker", "start", "gaia-sandbox-u1"]


async def test_a_failed_start_names_the_action(recorder: SpawnRecorder) -> None:
    recorder._responses = [
        _inspect_response(f"false {local_sandbox.LOCAL_SANDBOX_LAYOUT}"),
        FakeProcess(stderr=b"boom\n", returncode=1),
    ]
    with pytest.raises(LocalSandboxError) as raised:
        await _sandbox().ensure_started()
    assert str(raised.value) == "docker start failed for gaia-sandbox-u1: boom"


async def test_a_failed_run_names_the_action(recorder: SpawnRecorder, workspace_root: Path) -> None:
    recorder._responses = [
        FakeProcess(stderr=b"No such object", returncode=1),
        FakeProcess(returncode=0),
        FakeProcess(stderr=b"daemon unreachable\n", returncode=125),
    ]
    with pytest.raises(LocalSandboxError) as raised:
        await _sandbox().ensure_started()
    assert str(raised.value) == "docker run failed for gaia-sandbox-u1: daemon unreachable"


async def test_a_start_that_hangs_is_bounded(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_sandbox, "LOCAL_SANDBOX_START_TIMEOUT_SECONDS", 0.05)
    recorder._responses = [FakeProcess(hang=True)]
    start = asyncio.create_task(_sandbox().ensure_started())

    done, _ = await asyncio.wait({start}, timeout=5)

    assert done, "ensure_started never gave up on a hung docker call"
    with pytest.raises(TimeoutError):
        start.result()


async def test_a_fractional_timeout_is_accepted(recorder: SpawnRecorder) -> None:
    await _sandbox().set_timeout(0.5)
    assert recorder.argvs == []


async def test_pause_and_kill_target_the_users_container(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(), FakeProcess(stdout=b"gaia-sandbox-u1\n")]
    await _sandbox().beta_pause()
    await _sandbox().kill()
    assert recorder.argvs == [
        ["docker", "stop", "gaia-sandbox-u1"],
        ["docker", "rm", "-f", "gaia-sandbox-u1"],
    ]


async def test_undecodable_rm_output_is_replaced_not_fatal(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"\xff")]
    assert await _sandbox().kill() is False


async def test_background_commands_are_refused_with_the_alternative(
    recorder: SpawnRecorder,
) -> None:
    with pytest.raises(NotImplementedError) as raised:
        await _sandbox().commands.run("x", background=True)
    assert str(raised.value) == (
        "commands.run(background=True) is not supported by the local "
        "sandbox; detach inside the command itself (nohup … &)"
    )


async def test_no_timeout_runs_the_command_without_a_deadline(recorder: SpawnRecorder) -> None:
    recorder._responses = [FakeProcess(stdout=b"done")]
    result = await _sandbox().commands.run("slow", timeout=None)
    assert result.stdout == "done"
    assert "timeout" not in recorder.argv()


async def test_a_command_finishing_inside_the_grace_period_succeeds(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(local_sandbox, "_kill_process_group", killed.append)
    recorder._responses = [FakeProcess(stdout=b"ok", wait_delay=0.05)]
    result = await _sandbox().commands.run("quick", timeout=1)
    assert result.stdout == "ok"
    assert killed == []


async def test_a_killed_command_at_exactly_its_deadline_is_a_timeout(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = itertools.chain([100.0], itertools.repeat(160.0))
    monkeypatch.setattr(asyncio.get_running_loop(), "time", lambda: next(clock))
    long_cmd = "x" * 300
    recorder._responses = [FakeProcess(returncode=local_sandbox.LOCAL_SANDBOX_KILLED_EXIT_CODE)]
    with pytest.raises(TimeoutException) as raised:
        await _sandbox().commands.run(long_cmd, timeout=60)
    assert str(raised.value) == (
        f"command exceeded its 60s timeout and was killed: {long_cmd[:200]}"
    )


class _LateOutputProcess(FakeProcess):
    """Hangs until killed, then flushes a last line of output before its pipes close."""

    def kill(self) -> None:
        self.killed = True
        assert self._stdout is not None and self._stderr is not None
        self._stdout.feed_data(b"last words")
        self._stdout.feed_eof()
        self._stderr.feed_eof()


async def test_an_unresponsive_exec_reports_the_timeout_with_the_output_it_flushed(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _LateOutputProcess(hang=True)
    monkeypatch.setattr(local_sandbox, "_kill_process_group", lambda _pid: proc.kill())
    monkeypatch.setattr(local_sandbox, "LOCAL_SANDBOX_EXEC_TIMEOUT_GRACE_SECONDS", 0.05)
    recorder._responses = [proc]
    seen: list[str] = []
    long_cmd = "y" * 300

    with pytest.raises(TimeoutException) as raised:
        await _sandbox().commands.run(long_cmd, timeout=0.05, on_stdout=seen.append)

    assert seen == ["last words"]
    assert str(raised.value) == (
        f"command exceeded its 0.05s timeout and docker exec stopped responding: {long_cmd[:200]}"
    )


async def test_a_failing_output_callback_does_not_mask_the_timeout(
    recorder: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _LateOutputProcess(hang=True)
    monkeypatch.setattr(local_sandbox, "_kill_process_group", lambda _pid: proc.kill())
    monkeypatch.setattr(local_sandbox, "LOCAL_SANDBOX_EXEC_TIMEOUT_GRACE_SECONDS", 0.05)
    recorder._responses = [proc]

    def explode(_text: str) -> None:
        raise RuntimeError("callback broke")

    with pytest.raises(TimeoutException):
        await _sandbox().commands.run("hang", timeout=0.05, on_stdout=explode)


def test_popping_a_sandbox_hands_it_back_and_forgets_it() -> None:
    try:
        first = get_local_sandbox("pop-user")
        assert pop_local_sandbox("pop-user") is first
        assert get_local_sandbox("pop-user") is not first
    finally:
        pop_local_sandbox("pop-user")
