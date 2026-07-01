"""Shared execution for the read-only `grep` file-mining tool.

Resolves a workspace path with the same canonical resolver `read` uses, then runs
the binary over a SINGLE workspace file. Hardening (this runs in the API process,
not the sandbox):

- **No shell.** ``create_subprocess_exec`` takes an argv list, so the model's
  pattern is data, never parsed by a shell (`;`, `|`, `$()`, backticks, redirects
  cannot escape). The file is a separate, absolute-path arg, so it can't be read
  as a flag.
- **No inherited environment.** The child gets a minimal, secret-free env, so it
  can't exfiltrate the process environment (DB creds, Infisical secrets).
- **No stdin, absolute binary.** stdin is closed; the binary is resolved to an
  absolute path so PATH can't be hijacked.
- **Bounded.** A wall-clock timeout, a hard output cap, and child rlimits stop a
  pathological pattern (ReDoS) from hanging or OOMing the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import resource
import shutil
import sys

from langchain_core.runnables.config import RunnableConfig

from app.agents.tools.coding._context import canonical_path, get_session_id, get_user_id
from app.agents.workspace.paths import WORKSPACE_ROOT
from app.constants.log_tags import LogTag
from app.constants.offload import (
    FILTER_MAX_MEMORY_BYTES,
    FILTER_TIMEOUT_SECONDS,
    MAX_FILTER_OUTPUT_CHARS,
)
from app.services.storage import resolve_user_file
from shared.py.wide_events import log

# Read a little past the char cap (bytes ≈ chars) so multibyte output still fills
# the display budget before truncation.
_MAX_OUTPUT_BYTES = MAX_FILTER_OUTPUT_CHARS * 4
_MAX_STDERR_BYTES = 4096
_READ_CHUNK = 65536

# Minimal, secret-free environment for the child. PATH is unused (we exec an
# absolute path) but kept for any child that consults it; LC_ALL=C keeps byte
# handling predictable.
_SAFE_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}

_BIN_CACHE: dict[str, str] = {}


def _apply_child_limits() -> None:
    """Cap the child's memory/CPU/file-writes (runs post-fork, pre-exec).

    Defense-in-depth for the grep child: bound address space (RLIMIT_AS) and CPU,
    and RLIMIT_FSIZE=0 to enforce the read-only contract (stdout is a pipe, so it
    is unaffected).

    Each limit is set independently and tolerantly: macOS (dev) rejects
    ``RLIMIT_AS``, and a failure here would otherwise abort the whole exec. The
    memory ceiling is the one that matters in prod (Linux), where it applies.
    """
    limits = [
        (resource.RLIMIT_CPU, FILTER_TIMEOUT_SECONDS + 5),
        (resource.RLIMIT_FSIZE, 0),
    ]
    # RLIMIT_AS is the prod (Linux) memory ceiling; macOS (dev) rejects it with a
    # ValueError, so only attempt it where it's supported.
    if sys.platform == "linux":
        limits.append((resource.RLIMIT_AS, FILTER_MAX_MEMORY_BYTES))
    for res, limit in limits:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(res, (limit, limit))


def _resolve_binary(name: str) -> str:
    path = _BIN_CACHE.get(name)
    if path is None:
        path = shutil.which(name)
        if path is None:
            raise FileNotFoundError(f"{name} binary not available on host")
        _BIN_CACHE[name] = path
    return path


def _cap(text: str, *, truncated: bool) -> str:
    if truncated or len(text) > MAX_FILTER_OUTPUT_CHARS:
        return (
            text[:MAX_FILTER_OUTPUT_CHARS]
            + f"\n... [truncated at {MAX_FILTER_OUTPUT_CHARS} chars — narrow your query]"
        )
    return text


async def run_file_filter(
    *,
    config: RunnableConfig,
    binary: str,
    args: list[str],
    path: str,
    ok_returncodes: tuple[int, ...],
    empty_message: str,
    error_label: str,
) -> str:
    """Run ``binary args… <file>`` over ONE workspace file and return its output.

    ``ok_returncodes`` lists non-error exit codes (e.g. grep returns 1 for "no
    match"); ``empty_message`` is returned when the run succeeds with no output.
    """
    try:
        user_id = get_user_id(config)
        session_id = get_session_id(config)
        abs_path, _, _ = canonical_path(path, session_id=session_id)
    except ValueError as e:
        return f"Error: {e}"

    rel = abs_path[len(WORKSPACE_ROOT) + 1 :] if abs_path != WORKSPACE_ROOT else ""
    if not rel:
        return "Error: path must be a file inside the workspace, not the workspace root"

    try:
        program = _resolve_binary(binary)
        target = await resolve_user_file(user_id, rel)
        return await _run(program, args, str(target), ok_returncodes, empty_message, error_label)
    except FileNotFoundError as e:
        # Either the binary or the file is missing; the message says which.
        return f"Error: {e}"
    except Exception as e:
        log.error(f"{LogTag.SANDBOX} {error_label} tool failed: {e}", exc_info=True)
        return f"Error running {error_label}: {e}"


async def _run(
    program: str,
    args: list[str],
    target: str,
    ok_returncodes: tuple[int, ...],
    empty_message: str,
    error_label: str,
) -> str:
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        target,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_SAFE_ENV,
        preexec_fn=_apply_child_limits,  # noqa: PLW1509 — setrlimit only (sandboxing), no locks
    )
    try:
        out, err, truncated = await asyncio.wait_for(
            _read_bounded(proc), timeout=FILTER_TIMEOUT_SECONDS
        )
    except TimeoutError:
        await _terminate(proc)
        return f"Error: {error_label} timed out after {FILTER_TIMEOUT_SECONDS}s"

    # A truncated run is killed mid-stream (returncode is the kill signal), but we
    # already have enough output — return it rather than reporting the kill.
    if truncated:
        return _cap(out.decode("utf-8", "replace"), truncated=True)

    if proc.returncode not in ok_returncodes:
        msg = err.decode("utf-8", "replace").strip()
        return (
            f"{error_label} error: {msg}"
            if msg
            else f"{error_label} exited with code {proc.returncode}"
        )

    text = out.decode("utf-8", "replace")
    return _cap(text, truncated=False) if text else empty_message


async def _read_bounded(proc: asyncio.subprocess.Process) -> tuple[bytes, bytes, bool]:
    """Drain stdout (to the cap, killing on overrun) and stderr CONCURRENTLY.

    Reading stdout fully before stderr would deadlock: a child that fills the
    stderr pipe (64 KiB on Linux) blocks on its stderr write and never closes
    stdout, so the stdout read never sees EOF and the call wastes the full
    timeout. Draining both in parallel — and continuing to drain (discard) stderr
    past the kept cap — ensures the child can never back-pressure.
    """
    if proc.stdout is None:
        return b"", b"", False
    truncated = False

    async def drain_stdout() -> bytes:
        nonlocal truncated
        chunks: list[bytes] = []
        total = 0
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(_READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_OUTPUT_BYTES:
                truncated = True
                await _terminate(proc)
                break
        return b"".join(chunks)[:_MAX_OUTPUT_BYTES]

    async def drain_stderr() -> bytes:
        if proc.stderr is None:
            return b""
        kept = bytearray()
        while True:
            chunk = await proc.stderr.read(_READ_CHUNK)
            if not chunk:
                break
            if len(kept) < _MAX_STDERR_BYTES:
                kept.extend(chunk[: _MAX_STDERR_BYTES - len(kept)])
        return bytes(kept)

    out, err = await asyncio.gather(drain_stdout(), drain_stderr())
    await proc.wait()
    return out, err, truncated


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
            await proc.wait()
