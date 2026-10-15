"""Local Docker-exec sandbox: a drop-in stand-in for the E2B AsyncSandbox.

Self-host instances without an E2B key get per-user sibling containers with
the same commands and files surface the coding tools use. Results are genuine
E2B dataclasses and failures raise genuine E2B exceptions so existing handlers
keep matching.

Divergences are intentional: set timeout is a validated no-op, beta pause
stops the container, remove is idempotent, and background runs are rejected.
Like E2B's per-user JuiceFS subdir, a container mounts only its own user's
subtree of the workspace volume, so files survive recreation and no user can
reach another's.
"""

from __future__ import annotations

import asyncio
import codecs
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import errno
import hashlib
import io
import os
from pathlib import Path
import posixpath
import re
import signal
import tarfile
import time

from e2b import (
    CommandExitException,
    CommandResult,
    EntryInfo,
    NotFoundException,
    TimeoutException,
    WriteInfo,
)
from e2b.sandbox.filesystem.filesystem import FileType

from app.agents.workspace.paths import SKILLS_DIRNAME
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.sandbox import (
    LOCAL_SANDBOX_CONTAINER_PREFIX,
    LOCAL_SANDBOX_CPUS,
    LOCAL_SANDBOX_EXEC_TIMEOUT_GRACE_SECONDS,
    LOCAL_SANDBOX_HOME,
    LOCAL_SANDBOX_IMAGE,
    LOCAL_SANDBOX_KILLED_EXIT_CODE,
    LOCAL_SANDBOX_LAYOUT,
    LOCAL_SANDBOX_LAYOUT_LABEL,
    LOCAL_SANDBOX_MEMORY_LIMIT,
    LOCAL_SANDBOX_MEMORY_SWAP_LIMIT,
    LOCAL_SANDBOX_NETWORK,
    LOCAL_SANDBOX_NETWORK_ICC_OPTION,
    LOCAL_SANDBOX_PIDS_LIMIT,
    LOCAL_SANDBOX_START_TIMEOUT_SECONDS,
    LOCAL_SANDBOX_WORKSPACE_MOUNT,
    SELFHOST_WORKSPACE_VOLUME,
)
from app.services.storage.juicefs import (
    ensure_safe_path_id,
    ensure_user_skills_dir,
    ensure_user_workspace,
    user_skills_path,
    user_workspace_path,
)
from app.services.storage.system_workspace import SANDBOX_SYSTEM_DIR, SYSTEM_SUBDIR
from shared.py.wide_events import log

__all__ = [
    "CommandExitException",
    "LocalDockerSandbox",
    "LocalSandboxError",
    "NotFoundException",
    "TimeoutException",
    "container_name_for",
    "get_local_sandbox",
    "pop_local_sandbox",
]

# Marker in coreutils' error output that maps to e2b's NotFoundException.
_NOT_FOUND_MARKER = "No such file or directory"

# Docker daemon wording when the sandbox network was created by an earlier start.
_NETWORK_EXISTS_MARKER = "already exists"

# Docker daemon wording for an absent container. Older daemons say
# "No such object"; current ones name the object type.
_MISSING_CONTAINER_MARKERS = ("no such object", "no such container")

# Chunk size for streaming command output to on_stdout/on_stderr callbacks.
_STREAM_CHUNK_BYTES = 65_536

# stat(1) format for get_info: size|mode(hex)|permissions|owner|group|
# mtime(epoch)|type phrase. `-L` follows symlinks so callers see the target.
_STAT_FORMAT = "%s|%f|%a|%U|%G|%Y|%F"


class LocalSandboxError(RuntimeError):
    """A local-sandbox operation failed against the Docker daemon."""


def _raise_filetool_error(op: str, path: str, exit_code: int, stderr: str) -> None:
    """Translate a failed file op into the e2b-shaped error."""
    if _NOT_FOUND_MARKER in stderr:
        raise NotFoundException(f"{op}: {path}: no such file or directory")
    raise LocalSandboxError(f"docker {op} failed for {path} (exit {exit_code}): {stderr.strip()}")


def _tar_bytes(name: str, content: bytes) -> bytes:
    """Build an in-memory single-file tar for docker cp upload."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(content)
        info.mtime = int(time.time())
        # The sandbox runs as the API's uid; `docker cp --archive` keeps this owner.
        info.uid, info.gid = os.getuid(), os.getgid()
        tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _deliver(text: str, parts: list[str], callback: Callable[[str], None] | None) -> None:
    """Keep a decoded output piece and stream it to the caller; empty pieces are dropped."""
    if not text:
        return
    parts.append(text)
    if callback is not None:
        callback(text)


def _kill_process_group(pid: int) -> None:
    """SIGKILL a spawned command's whole process group (session leader = pid)."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass  # already dead — nothing to do
    except OSError as e:
        if e.errno != errno.ESRCH:
            log.warning(
                f"{LogTag.SANDBOX} failed to kill timed-out command group",
                pid=pid,
                error=str(e),
            )


def container_name_for(user_id: str) -> str:
    """Return the Docker container name for a user local sandbox.

    Unsafe characters collapse to dashes with a short digest suffix so two users
    can never share a container after sanitization.
    """
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", user_id).strip("-.") or "user"
    if clean != user_id:
        # Non-crypto fingerprint: only disambiguates sanitized names.
        digest = hashlib.sha256(user_id.encode()).hexdigest()[:8]
        clean = f"{clean}-{digest}"
    return f"{LOCAL_SANDBOX_CONTAINER_PREFIX}{clean}"


@dataclass(frozen=True)
class _ContainerState:
    """Result of inspecting a container; layout is its LOCAL_SANDBOX_LAYOUT_LABEL value."""

    exists: bool
    running: bool
    layout: str = ""


_MISSING_CONTAINER = _ContainerState(exists=False, running=False)


@dataclass(frozen=True)
class _WorkspaceMount:
    """One subtree of the workspace volume and where the container sees it."""

    source: Path
    target: str
    read_only: bool = False


# The container's view of the workspace volume, mirroring mount_juicefs.sh's
# E2B layout: the user's root read-write, their skills and the shared system
# files read-only on top. Nothing else on the volume is ever mounted.
def _workspace_mounts(user_id: str) -> tuple[_WorkspaceMount, ...]:
    return (
        _WorkspaceMount(user_workspace_path(user_id), LOCAL_SANDBOX_WORKSPACE_MOUNT),
        _WorkspaceMount(
            user_skills_path(user_id), f"{LOCAL_SANDBOX_WORKSPACE_MOUNT}/{SKILLS_DIRNAME}", True
        ),
        _WorkspaceMount(
            Path(settings.JUICEFS_HOST_MOUNT_PATH) / SYSTEM_SUBDIR, SANDBOX_SYSTEM_DIR, True
        ),
    )


def _mount_arg(mount: _WorkspaceMount) -> str:
    subpath = mount.source.relative_to(settings.JUICEFS_HOST_MOUNT_PATH).as_posix()
    spec = (
        f"type=volume,src={SELFHOST_WORKSPACE_VOLUME},dst={mount.target},volume-subpath={subpath}"
    )
    return f"{spec},readonly" if mount.read_only else spec


def _make_mount_sources(user_id: str) -> None:
    """Create every mounted subpath and nested mountpoint; the daemon refuses missing ones."""
    user_root = user_workspace_path(user_id)
    for mount in _workspace_mounts(user_id):
        mount.source.mkdir(exist_ok=True)
        if mount.target != LOCAL_SANDBOX_WORKSPACE_MOUNT:
            nested = posixpath.relpath(mount.target, LOCAL_SANDBOX_WORKSPACE_MOUNT)
            (user_root / nested).mkdir(exist_ok=True)


async def _spawn_process(
    argv: list[str], *, stdin: bytes | None = None
) -> asyncio.subprocess.Process:
    """Spawn a host subprocess. Single seam tests patch instead of real Docker."""
    return await asyncio.create_subprocess_exec(  # NOSONAR python:S603 — argv list is fully constructed, never a shell string
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


class LocalDockerSandbox:
    """Per-user sandbox backed by docker exec against a sibling container.

    One instance per user per process holding no durable state, so a restarted
    process re-inspects and recreates containers on demand.
    """

    def __init__(
        self,
        user_id: str,
        *,
        image: str = LOCAL_SANDBOX_IMAGE,
    ) -> None:
        if not user_id:
            raise ValueError("user_id is required")
        self.user_id = user_id
        self.image = image
        # Guards ensure_started() against concurrent first acquires racing two
        # `docker run`s into a name clash.
        self._start_lock = asyncio.Lock()

    @property
    def container_name(self) -> str:
        return container_name_for(self.user_id)

    # e2b exposes an opaque sandbox id; ours is the container name, which is
    # what logs should carry for local debugging anyway.
    @property
    def sandbox_id(self) -> str:
        return self.container_name

    def __repr__(self) -> str:
        return f"<LocalDockerSandbox {self.container_name}>"

    # ── low-level docker plumbing ────────────────────────────────────────

    async def _run_docker(self, *args: str, stdin: bytes | None = None) -> tuple[int, bytes, str]:
        """Run docker with the given args on the host and return exit code and output."""
        proc = await _spawn_process(["docker", *args], stdin=stdin)
        stdout, stderr = await proc.communicate(stdin)
        return proc.returncode or 0, stdout, stderr.decode(errors="replace")

    async def _exec_argv(
        self,
        cmd_args: list[str],
        *,
        user: str | None = None,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> list[str]:
        """Build docker exec argv for a container command, never a shell string."""
        argv = ["exec"]
        if user:
            argv += ["--user", user]
        for key, value in (envs or {}).items():
            argv += ["--env", f"{key}={value}"]
        if cwd:
            argv += ["--workdir", cwd]
        return [*argv, self.container_name, *cmd_args]

    async def _exec_capture(self, cmd_args: list[str]) -> tuple[int, bytes, str]:
        """Run a command inside the container, capturing (exit_code, stdout, stderr)."""
        return await self._run_docker(*await self._exec_argv(cmd_args))

    # ── container lifecycle ──────────────────────────────────────────────

    async def _container_state(self) -> _ContainerState:
        rc, stdout, stderr = await self._run_docker(
            "container",
            "inspect",
            "-f",
            f'{{{{.State.Running}}}} {{{{index .Config.Labels "{LOCAL_SANDBOX_LAYOUT_LABEL}"}}}}',
            self.container_name,
        )
        if rc != 0:
            stderr_lower = stderr.lower()
            if any(marker in stderr_lower for marker in _MISSING_CONTAINER_MARKERS):
                return _MISSING_CONTAINER
            raise LocalSandboxError(
                f"docker inspect failed for {self.container_name}: {stderr.strip()}"
            )
        running, _, layout = stdout.decode(errors="replace").strip().partition(" ")
        return _ContainerState(exists=True, running=running.lower() == "true", layout=layout)

    async def _prepare_workspace(self) -> None:
        """Validate the user id for the mount spec and create its subpaths on the volume.

        Raises JuiceFSUnavailable when the workspace volume is not mounted, so a
        sandbox never starts without its user's files.
        """
        ensure_safe_path_id(self.user_id, label="user_id")
        await ensure_user_workspace(self.user_id)
        await ensure_user_skills_dir(self.user_id)
        await asyncio.to_thread(_make_mount_sources, self.user_id)

    async def _ensure_network(self) -> None:
        """Create the isolated sandbox bridge network unless an earlier start did."""
        rc, _, stderr = await self._run_docker(
            "network",
            "create",
            "--driver",
            "bridge",
            "--opt",
            LOCAL_SANDBOX_NETWORK_ICC_OPTION,
            LOCAL_SANDBOX_NETWORK,
        )
        if rc != 0 and _NETWORK_EXISTS_MARKER not in stderr:
            raise LocalSandboxError(
                f"docker network create failed for {LOCAL_SANDBOX_NETWORK}: {stderr.strip()}"
            )

    async def _create_container(self) -> tuple[int, str]:
        await self._prepare_workspace()
        await self._ensure_network()
        mount_args = [
            arg
            for mount in _workspace_mounts(self.user_id)
            for arg in ("--mount", _mount_arg(mount))
        ]
        rc, _, stderr = await self._run_docker(
            "run",
            "-d",
            "--name",
            self.container_name,
            "--label",
            f"gaia.sandbox.user={self.user_id}",
            "--label",
            f"{LOCAL_SANDBOX_LAYOUT_LABEL}={LOCAL_SANDBOX_LAYOUT}",
            *mount_args,
            "--network",
            LOCAL_SANDBOX_NETWORK,
            "--memory",
            LOCAL_SANDBOX_MEMORY_LIMIT,
            "--memory-swap",
            LOCAL_SANDBOX_MEMORY_SWAP_LIMIT,
            "--pids-limit",
            str(LOCAL_SANDBOX_PIDS_LIMIT),
            "--cpus",
            LOCAL_SANDBOX_CPUS,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            # Same uid as the API, so files either side creates stay writable by both.
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            f"HOME={LOCAL_SANDBOX_HOME}",
            "--restart",
            "unless-stopped",
            self.image,
            "sleep",
            "infinity",
        )
        return rc, stderr

    async def ensure_started(self) -> None:
        """Start the user container, creating it on first acquire.

        Idempotent across running, stopped, and missing states; bounded so a cold
        image pull cannot stall the agent indefinitely.
        """
        async with self._start_lock, asyncio.timeout(LOCAL_SANDBOX_START_TIMEOUT_SECONDS):
            state = await self._container_state()
            if state.exists and state.layout != LOCAL_SANDBOX_LAYOUT:
                # Created before per-user isolation: it mounts every user's files.
                log.info(
                    f"{LogTag.SANDBOX} replacing local container from an older mount layout",
                    container=self.container_name,
                    layout=state.layout,
                )
                await self.kill()
                state = _MISSING_CONTAINER
            if not state.running:
                if state.exists:
                    rc, _, stderr = await self._run_docker("start", self.container_name)
                    action = "start"
                else:
                    rc, stderr = await self._create_container()
                    action = "run"
                if rc != 0:
                    raise LocalSandboxError(
                        f"docker {action} failed for {self.container_name}: {stderr.strip()}"
                    )
                state = await self._container_state()
                if not state.running:
                    raise LocalSandboxError(
                        f"container {self.container_name} did not reach 'running' state after start"
                    )
        log.info(
            f"{LogTag.SANDBOX} local container ready",
            container=self.container_name,
            user_id=self.user_id,
        )

    async def is_running(self, request_timeout: float | None = None) -> bool:
        """Return True while the container exists and runs, False when missing.

        The request timeout arg exists for interface parity only and is ignored.
        """
        del request_timeout
        try:
            state = await self._container_state()
        except LocalSandboxError as e:
            log.warning(
                f"{LogTag.SANDBOX} liveness probe failed; reporting dead",
                container=self.container_name,
                error=str(e),
            )
            return False
        return state.running

    async def set_timeout(self, timeout: float) -> None:
        """Validate the timeout as a no-op; local containers have no kill timer.

        Parity with E2B only: the container persists until kill or host shutdown.
        """
        if float(timeout) <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

    async def beta_pause(self) -> None:
        """Stop the container (its files survive on the workspace volume)."""
        rc, _, stderr = await self._run_docker("stop", self.container_name)
        if rc != 0:
            raise LocalSandboxError(
                f"docker stop failed for {self.container_name}: {stderr.strip()}"
            )

    async def kill(self) -> bool:
        """Force-remove the container. False (never raises) if already gone."""
        rc, stdout, stderr = await self._run_docker("rm", "-f", self.container_name)
        if rc == 0:
            # Docker 29 exits 0 for a forced remove of a missing container, silently or
            # with "No such container"; only an actual removal echoes the name.
            removed = stdout.decode(errors="replace").strip() == self.container_name
            if not removed:
                log.info(
                    f"{LogTag.SANDBOX} local container already gone",
                    container=self.container_name,
                )
                return False
            return True
        if any(m in stderr.lower() for m in _MISSING_CONTAINER_MARKERS):
            return False
        raise LocalSandboxError(f"docker rm failed for {self.container_name}: {stderr.strip()}")

    # ── commands ─────────────────────────────────────────────────────────

    class CommandsFacade:
        """Namespace for the commands run entrypoint."""

        def __init__(self, sandbox: LocalDockerSandbox) -> None:
            self._sandbox = sandbox

        async def run(
            self,
            cmd: str,
            *,
            background: bool | None = None,
            envs: dict[str, str] | None = None,
            user: str | None = None,
            cwd: str | None = None,
            on_stdout: Callable[[str], None] | None = None,
            on_stderr: Callable[[str], None] | None = None,
            timeout: float | None = 60,
        ) -> CommandResult:
            return await self._sandbox.commands_run(
                cmd,
                background=background,
                envs=envs,
                user=user,
                cwd=cwd,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
                timeout=timeout,
            )

    @property
    def commands(self) -> CommandsFacade:
        return LocalDockerSandbox.CommandsFacade(self)

    async def commands_run(
        self,
        cmd: str,
        *,
        background: bool | None,
        envs: dict[str, str] | None,
        user: str | None,
        cwd: str | None,
        on_stdout: Callable[[str], None] | None,
        on_stderr: Callable[[str], None] | None,
        timeout: float | None,
    ) -> CommandResult:
        """Run a command in the container through a login shell.

        Non-zero exits raise CommandExitException with captured output. The
        timeout is enforced inside the container, where killing the command's
        process group actually stops it; exceeding it raises TimeoutException.
        """
        if background:
            raise NotImplementedError(
                "commands.run(background=True) is not supported by the local "
                "sandbox; detach inside the command itself (nohup … &)"
            )
        deadline = timeout if timeout is not None and timeout > 0 else None
        # e2b runs commands through a login shell (`bash -l -c`) so profile
        # environment is present — mirror it exactly.
        shell = ["/bin/bash", "-l", "-c", cmd]
        if deadline is not None:
            shell = ["timeout", "--signal=KILL", f"{deadline}s", *shell]
        argv = ["docker", *await self._exec_argv(shell, user=user, envs=envs, cwd=cwd)]
        loop = asyncio.get_running_loop()
        started = loop.time()
        proc = await _spawn_process(argv)
        # _spawn_process always pipes both streams; this only narrows the types.
        assert proc.stdout is not None and proc.stderr is not None  # pragma: no mutate

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        async def pump(
            stream: asyncio.StreamReader,
            parts: list[str],
            callback: Callable[[str], None] | None,
        ) -> None:
            # Incremental, so a multi-byte character split across two reads decodes whole.
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while chunk := await stream.read(_STREAM_CHUNK_BYTES):
                _deliver(decoder.decode(chunk), parts, callback)
            _deliver(decoder.decode(b"", final=True), parts, callback)

        pumps = [
            asyncio.create_task(pump(proc.stdout, stdout_parts, on_stdout)),
            asyncio.create_task(pump(proc.stderr, stderr_parts, on_stderr)),
        ]
        waiter = asyncio.create_task(proc.wait())
        host_deadline = (
            deadline + LOCAL_SANDBOX_EXEC_TIMEOUT_GRACE_SECONDS if deadline is not None else None
        )
        _, pending = await asyncio.wait({*pumps, waiter}, timeout=host_deadline)
        if pending:
            # The in-container timeout should already have fired; the daemon is
            # unresponsive, so drop the exec client rather than hang the agent.
            _kill_process_group(proc.pid)
            await proc.wait()
            await asyncio.gather(*pumps, return_exceptions=True)
            waiter.cancel()
            raise TimeoutException(
                f"command exceeded its {timeout}s timeout and docker exec stopped responding: "
                f"{cmd[:200]}"
            )

        await asyncio.gather(*pumps)
        exit_code = waiter.result()
        stdout_str = "".join(stdout_parts)
        stderr_str = "".join(stderr_parts)
        if (
            deadline is not None
            and exit_code == LOCAL_SANDBOX_KILLED_EXIT_CODE
            and loop.time() - started >= deadline
        ):
            raise TimeoutException(
                f"command exceeded its {timeout}s timeout and was killed: {cmd[:200]}"
            )
        if exit_code != 0:
            raise CommandExitException(
                stderr=stderr_str, stdout=stdout_str, exit_code=exit_code, error=None
            )
        return CommandResult(stderr=stderr_str, stdout=stdout_str, exit_code=exit_code, error=None)

    # ── files ────────────────────────────────────────────────────────────

    class FilesFacade:
        """Namespace for the files entrypoints."""

        def __init__(self, sandbox: LocalDockerSandbox) -> None:
            self._sandbox = sandbox

        async def read(self, path: str, format: str = "text") -> str | bytes:
            """Read a file byte-exact; missing paths raise NotFoundException."""
            if format not in ("text", "bytes"):
                raise ValueError(f"unsupported read format: {format!r}")
            exit_code, stdout, stderr = await self._sandbox._exec_capture(["cat", "--", path])
            if exit_code != 0:
                _raise_filetool_error("files.read", path, exit_code, stderr)
            return stdout.decode(errors="replace") if format == "text" else stdout

        async def write(self, path: str, data: str | bytes) -> WriteInfo:
            """Write content via tar stream; parents are created first like E2B.

            Content never passes through a shell, so any bytes are safe.
            """
            if isinstance(data, str):
                data = data.encode("utf-8")
            elif not isinstance(data, bytes):
                raise TypeError(f"files.write expects str or bytes, got {type(data).__name__}")
            parent = posixpath.dirname(path)
            name = posixpath.basename(path)
            if not parent.startswith("/"):
                raise ValueError(f"files.write requires an absolute path, got {path!r}")
            if not name:
                raise ValueError(f"files.write path must name a file, got {path!r}")
            sbx = self._sandbox
            exit_code, _, stderr = await sbx._exec_capture(["mkdir", "-p", "--", parent])
            if exit_code != 0:
                _raise_filetool_error("files.write(mkdir)", parent, exit_code, stderr)
            # docker cp is a host-side command (not an exec): stream the tar in
            # on stdin and unpack it straight into the parent directory.
            exit_code, _, stderr = await sbx._run_docker(
                "cp",
                "--archive",
                "-",
                f"{sbx.container_name}:{parent}",
                stdin=_tar_bytes(name, data),
            )
            if exit_code != 0:
                _raise_filetool_error("files.write(cp)", path, exit_code, stderr)
            return WriteInfo(name=name, type=FileType.FILE, path=path)

        async def rename(self, old_path: str, new_path: str) -> EntryInfo:
            """Move an entry; returns the new location's metadata like e2b."""
            sbx = self._sandbox
            exit_code, _, stderr = await sbx._exec_capture(["mv", "--", old_path, new_path])
            if exit_code != 0:
                _raise_filetool_error(
                    "files.rename", f"{old_path} -> {new_path}", exit_code, stderr
                )
            return await self.get_info(new_path)

        async def remove(self, path: str) -> None:
            """Delete a path idempotently; missing paths succeed."""
            exit_code, _, stderr = await self._sandbox._exec_capture(["rm", "-rf", "--", path])
            if exit_code != 0:
                _raise_filetool_error("files.remove", path, exit_code, stderr)

        async def make_dir(self, path: str) -> bool:
            """Create a path and any missing parents, always returning True."""
            exit_code, _, stderr = await self._sandbox._exec_capture(["mkdir", "-p", "--", path])
            if exit_code != 0:
                _raise_filetool_error("files.make_dir", path, exit_code, stderr)
            return True

        async def get_info(self, path: str) -> EntryInfo:
            """Stat an entry into an E2B EntryInfo with naive UTC modified time.

            Naive matches the E2B timestamp behavior callers already expect.
            """
            exit_code, stdout, stderr = await self._sandbox._exec_capture(
                ["stat", "-L", "-c", _STAT_FORMAT, "--", path]
            )
            if exit_code != 0:
                _raise_filetool_error("files.get_info", path, exit_code, stderr)
            fields = stdout.decode(errors="replace").strip().split("|")
            if len(fields) != 7:
                raise LocalSandboxError(f"unexpected stat output for {path}: {stdout!r}")
            size_s, mode_hex, perms, owner, group, epoch_s, kind = fields
            modified_time = datetime.fromtimestamp(int(epoch_s), tz=UTC).replace(tzinfo=None)
            return EntryInfo(
                name=posixpath.basename(path.rstrip("/")) or path,
                type=FileType.DIR if "directory" in kind else FileType.FILE,
                path=path,
                size=int(size_s),
                mode=int(mode_hex, 16),
                permissions=perms,
                owner=owner,
                group=group,
                modified_time=modified_time,
                symlink_target=None,
            )

    @property
    def files(self) -> FilesFacade:
        return LocalDockerSandbox.FilesFacade(self)


# ── per-process registry ────────────────────────────────────────────────────

_local_sandboxes: dict[str, LocalDockerSandbox] = {}


def get_local_sandbox(user_id: str) -> LocalDockerSandbox:
    """Return the process-wide LocalDockerSandbox for a user, creating on demand."""
    sbx = _local_sandboxes.get(user_id)
    if sbx is None:
        sbx = LocalDockerSandbox(user_id)
        _local_sandboxes[user_id] = sbx
    return sbx


def pop_local_sandbox(user_id: str) -> LocalDockerSandbox | None:
    """Drop a user's cached sandbox handle (used on death-eviction)."""
    return _local_sandboxes.pop(user_id, None)
