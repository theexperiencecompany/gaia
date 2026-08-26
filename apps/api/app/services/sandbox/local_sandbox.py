"""Local Docker-exec sandbox — a drop-in stand-in for `e2b.AsyncSandbox`.

Self-host instances usually have no E2B API key. This module gives them real
code execution by shelling out to the host's Docker daemon: each user gets a
dedicated sibling container (``gaia-sandbox-<user_id>``) and every sandbox
operation is one `docker exec` / `docker cp` invocation away.

Interface contract (mirrors the e2b surface the coding tools actually use):

    sbx.commands.run(cmd, *, background, envs, user, cwd, on_stdout,
                     on_stderr, timeout)
        → CommandResult(.exit_code, .stdout, .stderr); raises
          CommandExitException on non-zero exit, TimeoutException on timeout.
    sbx.files.read(path, format="text" | "bytes")  → raises NotFoundException
    sbx.files.write(path, data: str | bytes)       → WriteInfo
    sbx.files.rename(src, dst)                     → EntryInfo
    sbx.files.remove(path) / make_dir(path) / get_info(path) → EntryInfo
    sbx.is_running(request_timeout=None), set_timeout(seconds),
    sbx.beta_pause(), sbx.kill(), sbx.sandbox_id

Types, deliberately NOT re-implemented: results are genuine e2b dataclasses
(``CommandResult``, ``WriteInfo``, ``EntryInfo``) and failures raise the
genuine e2b exceptions. The tools catch ``e2b.CommandExitException`` /
``e2b.TimeoutException`` / ``e2b.NotFoundException`` directly — a parallel
local hierarchy would sail past those handlers and turn normal non-zero exits
into tool errors. They are re-exported below so callers of this module need no
e2b import.

Divergences from E2B, all intentional:
  - ``set_timeout`` is a validated no-op: plain containers have no server-side
    kill timer; lifetime is managed by the compose restart policy and explicit
    ``kill()``.
  - ``beta_pause`` stops the container: filesystem state survives (it lives on
    a shared named volume) but in-memory processes do not — irrelevant here,
    since nothing in this codebase resumes a paused process tree.
  - ``files.remove`` is idempotent (``rm -rf`` semantics): deleting an absent
    path succeeds instead of raising NotFoundException.
  - ``commands.run(background=True)`` is rejected loudly: no current caller
    uses it (bash_tool detaches via nohup inside the command itself), and a
    fake handle would be worse than an honest error.

Workspace durability: every container mounts the shared named volume
``LOCAL_SANDBOX_VOLUME`` at ``/workspace``, so files survive container
recreation (kill → next acquire starts a fresh container).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import errno
import hashlib
import io
import os
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

from app.constants.log_tags import LogTag
from app.constants.sandbox import (
    LOCAL_SANDBOX_CONTAINER_PREFIX,
    LOCAL_SANDBOX_IMAGE,
    LOCAL_SANDBOX_START_TIMEOUT_SECONDS,
    LOCAL_SANDBOX_VOLUME,
    LOCAL_SANDBOX_WORKSPACE_MOUNT,
)
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
    """Build an in-memory single-file tar for `docker cp - <container>:<dir>`."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(content)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


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
    """Return the Docker container name for a user's local sandbox.

    Container names only allow ``[a-zA-Z0-9][a-zA-Z0-9_.-]*``; user ids are not
    guaranteed to fit, so anything else is collapsed to ``-``. A short digest
    suffix keeps distinct users from colliding after sanitization — sharing a
    container would be cross-user workspace contamination.
    """
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", user_id).strip("-.") or "user"
    if clean != user_id:
        # Non-crypto fingerprint: only disambiguates sanitized names.
        digest = hashlib.sha1(user_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        clean = f"{clean}-{digest}"
    return f"{LOCAL_SANDBOX_CONTAINER_PREFIX}{clean}"


@dataclass(frozen=True)
class _ContainerState:
    """Result of inspecting a container."""

    exists: bool
    running: bool


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
    """Per-user sandbox backed by `docker exec` against a sibling container.

    One instance per user per API process (see :func:`get_local_sandbox`).
    Instances hold no durable state — everything lives in the Docker daemon
    and the shared workspace volume — so a restarted API process simply
    re-inspects and reuses (or recreates) containers on demand.
    """

    def __init__(
        self,
        user_id: str,
        *,
        image: str = LOCAL_SANDBOX_IMAGE,
        volume: str = LOCAL_SANDBOX_VOLUME,
    ) -> None:
        if not user_id:
            raise ValueError("user_id is required")
        self.user_id = user_id
        self.image = image
        self.volume = volume
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
        """Run `docker <args>` on the host; return (exit_code, stdout_bytes, stderr_text)."""
        proc = await _spawn_process(["docker", *args], stdin=stdin)
        stdout, stderr = await proc.communicate(stdin)
        return proc.returncode or 0, stdout, stderr.decode("utf-8", errors="replace")

    async def _exec_argv(
        self,
        cmd_args: list[str],
        *,
        user: str | None = None,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> list[str]:
        """Build `docker exec ... <container> <cmd_args>` argv (never a shell)."""
        argv = ["exec"]
        if user:
            argv += ["--user", user]
        for key, value in (envs or {}).items():
            argv += ["--env", f"{key}={value}"]
        if cwd:
            argv += ["--workdir", cwd]
        return [*argv, self.container_name, *cmd_args]

    async def _exec_capture(
        self,
        cmd_args: list[str],
        *,
        user: str | None = None,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> tuple[int, bytes, str]:
        """Run a command inside the container, capturing (exit_code, stdout, stderr)."""
        argv = await self._exec_argv(cmd_args, user=user, envs=envs, cwd=cwd)
        return await self._run_docker(*argv)

    # ── container lifecycle ──────────────────────────────────────────────

    async def _container_state(self) -> _ContainerState:
        rc, stdout, stderr = await self._run_docker(
            "container", "inspect", "-f", "{{.State.Running}}", self.container_name
        )
        if rc != 0:
            stderr_lower = stderr.lower()
            if any(marker in stderr_lower for marker in _MISSING_CONTAINER_MARKERS):
                return _ContainerState(exists=False, running=False)
            raise LocalSandboxError(
                f"docker inspect failed for {self.container_name}: {stderr.strip()}"
            )
        return _ContainerState(
            exists=True,
            running=stdout.decode("utf-8", errors="replace").strip().lower() == "true",
        )

    async def ensure_started(self) -> None:
        """Start the user's container, creating it on first ever acquire.

        Idempotent: a running container is left untouched, a stopped one is
        started (after beta_pause or a manual `docker stop`), a missing one is
        created from the lightweight image with the shared workspace volume
        mounted. Bounded end-to-end so a cold image pull can't stall the agent
        indefinitely.
        """
        async with self._start_lock, asyncio.timeout(LOCAL_SANDBOX_START_TIMEOUT_SECONDS):
            state = await self._container_state()
            if not state.running:
                if state.exists:
                    rc, _, stderr = await self._run_docker("start", self.container_name)
                    action = "start"
                else:
                    rc, _, stderr = await self._run_docker(
                        "run",
                        "-d",
                        "--name",
                        self.container_name,
                        "--label",
                        f"gaia.sandbox.user={self.user_id}",
                        "--volume",
                        f"{self.volume}:{LOCAL_SANDBOX_WORKSPACE_MOUNT}",
                        "--restart",
                        "unless-stopped",
                        self.image,
                        "sleep",
                        "infinity",
                    )
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
        """True while the container exists and runs. Missing ⇒ False.

        ``request_timeout`` is accepted for interface parity with e2b and
        ignored: callers already bound this externally (the lifecycle health
        probe wraps it in ``asyncio.wait_for``).
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
        """Validated no-op: local containers have no server-side kill timer.

        Interface parity with e2b — the lifecycle calls this on reuse to keep
        an actively-used cloud sandbox alive. Nothing expires server-side here;
        the container persists until ``kill()``, the compose restart policy, or
        the host goes down.
        """
        if float(timeout) <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

    async def beta_pause(self) -> None:
        """Stop the container (filesystem survives on the shared volume)."""
        rc, _, stderr = await self._run_docker("stop", self.container_name)
        if rc != 0:
            raise LocalSandboxError(
                f"docker stop failed for {self.container_name}: {stderr.strip()}"
            )

    async def kill(self) -> bool:
        """Force-remove the container. False (never raises) if already gone."""
        rc, _, stderr = await self._run_docker("rm", "-f", self.container_name)
        if rc == 0:
            # Some daemons exit 0 even when printing "No such container" for a
            # forced remove of a missing container — trust stderr over rc.
            if any(m in stderr.lower() for m in _MISSING_CONTAINER_MARKERS):
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
        """`sbx.commands.run(...)` namespace."""

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
        background: bool | None = None,
        envs: dict[str, str] | None = None,
        user: str | None = None,
        cwd: str | None = None,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        timeout: float | None = 60,
    ) -> CommandResult:
        """Run `cmd` in the container via `/bin/bash -l -c` (e2b parity).

        Streams decoded chunks to ``on_stdout``/``on_stderr`` as they arrive.
        Non-zero exits raise ``CommandExitException`` carrying the captured
        output (the tools rely on this to treat failing commands as results);
        exceeding ``timeout`` kills the whole process group and raises
        ``TimeoutException``. ``None`` or ``0`` disables the deadline.
        """
        if background:
            raise NotImplementedError(
                "commands.run(background=True) is not supported by the local "
                "sandbox; detach inside the command itself (nohup … &)"
            )
        # e2b runs commands through a login shell (`bash -l -c`) so profile
        # environment is present — mirror it exactly.
        argv = [
            "docker",
            *await self._exec_argv(["/bin/bash", "-l", "-c", cmd], user=user, envs=envs, cwd=cwd),
        ]
        proc = await _spawn_process(argv)
        assert proc.stdout is not None and proc.stderr is not None

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        async def pump(
            stream: asyncio.StreamReader,
            parts: list[str],
            callback: Callable[[str], None] | None,
        ) -> None:
            while chunk := await stream.read(_STREAM_CHUNK_BYTES):
                text = chunk.decode("utf-8", errors="replace")
                parts.append(text)
                if callback is not None:
                    callback(text)

        pumps = [
            asyncio.create_task(pump(proc.stdout, stdout_parts, on_stdout)),
            asyncio.create_task(pump(proc.stderr, stderr_parts, on_stderr)),
        ]
        waiter = asyncio.create_task(proc.wait())
        deadline = timeout if timeout and timeout > 0 else None
        _, pending = await asyncio.wait({*pumps, waiter}, timeout=deadline)
        if pending:
            # Deadline hit: SIGKILL the session leader's group so children of
            # the shell die too, then drain before raising.
            _kill_process_group(proc.pid)
            await proc.wait()
            await asyncio.gather(*pumps, return_exceptions=True)
            waiter.cancel()
            raise TimeoutException(
                f"command exceeded its {timeout}s timeout and was killed: {cmd[:200]}"
            )

        await asyncio.gather(*pumps)
        exit_code = waiter.result()
        stdout_str = "".join(stdout_parts)
        stderr_str = "".join(stderr_parts)
        if exit_code != 0:
            raise CommandExitException(
                stderr=stderr_str, stdout=stdout_str, exit_code=exit_code, error=None
            )
        return CommandResult(stderr=stderr_str, stdout=stdout_str, exit_code=exit_code, error=None)

    # ── files ────────────────────────────────────────────────────────────

    class FilesFacade:
        """`sbx.files.*` namespace."""

        def __init__(self, sandbox: LocalDockerSandbox) -> None:
            self._sandbox = sandbox

        async def read(self, path: str, format: str = "text") -> str | bytes:
            """Read a file through `cat` (byte-exact, binary-safe).

            Missing paths raise NotFoundException; any other failure is a loud
            LocalSandboxError rather than a silent empty read.
            """
            if format not in ("text", "bytes"):
                raise ValueError(f"unsupported read format: {format!r}")
            exit_code, stdout, stderr = await self._sandbox._exec_capture(["cat", "--", path])
            if exit_code != 0:
                _raise_filetool_error("files.read", path, exit_code, stderr)
            return stdout.decode("utf-8", errors="replace") if format == "text" else stdout

        async def write(self, path: str, data: str | bytes) -> WriteInfo:
            """Write content via one-file tar piped through `docker cp`.

            Creates the parent directory first (matches e2b's auto-mkdir; the
            canary and run-log writes depend on it). Bytes ride as a tar
            stream on stdin — never through a shell, so any content is safe.
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
            """Idempotent delete (`rm -rf`)."""
            exit_code, _, stderr = await self._sandbox._exec_capture(["rm", "-rf", "--", path])
            if exit_code != 0:
                _raise_filetool_error("files.remove", path, exit_code, stderr)

        async def make_dir(self, path: str) -> bool:
            """Create ``path`` and any missing parents. Always True."""
            exit_code, _, stderr = await self._sandbox._exec_capture(["mkdir", "-p", "--", path])
            if exit_code != 0:
                _raise_filetool_error("files.make_dir", path, exit_code, stderr)
            return True

        async def get_info(self, path: str) -> EntryInfo:
            """Stat an entry into an e2b EntryInfo (naive-UTC modified_time).

            ``modified_time`` is deliberately naive UTC — e2b's protobuf
            Timestamp.ToDatetime() behaves the same, and ``atomic_write``
            re-tags UTC before computing epochs.
            """
            exit_code, stdout, stderr = await self._sandbox._exec_capture(
                ["stat", "-L", "-c", _STAT_FORMAT, "--", path]
            )
            if exit_code != 0:
                _raise_filetool_error("files.get_info", path, exit_code, stderr)
            fields = stdout.decode("utf-8", errors="replace").strip().split("|")
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
