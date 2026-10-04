"""A hermetic stand-in for e2b's AsyncSandbox: real bash, real files, no E2B.

FakeAsyncSandbox executes ``commands.run`` through a local ``bash -c`` in a
temp dir (every ``/workspace`` prefix rewritten to that dir, ``HOME`` pointed
at it, dummy ``claude``/``opencode`` shims on ``PATH`` so the seed's
install-if-missing lines stay offline) and implements ``files.make_dir`` /
``write`` / ``read`` on the real filesystem. Non-zero exits raise
``CommandExitException`` exactly like the SDK, so tool error paths stay honest.

What this proves: the seed script build_seed_command builds is executable and writes
the files it claims (hooks fragment, settings merge, lab-env, plugin). What
it does NOT prove: cold-boot time, the JuiceFS mount (no FUSE here), pause /
resume and canary staleness, the template image's preinstalled CLIs, or hook
delivery over the E2B network.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Any, ClassVar
from uuid import uuid4

from e2b import CommandExitException


class _FakeFiles:
    """File ops on the real FS, with the sandbox's /workspace prefix rewritten."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _resolve(self, path: str) -> Path:
        return Path(path.replace("/workspace", str(self._root)))

    async def make_dir(self, path: str) -> None:
        await asyncio.to_thread(self._resolve(path).mkdir, True, True)

    async def write(self, path: str, content: str | bytes) -> None:
        target = self._resolve(path)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content)

        await asyncio.to_thread(_write)

    async def read(self, path: str) -> str:
        return await asyncio.to_thread(self._resolve(path).read_text)


class _FakeCommands:
    """Shell ops via local bash; the seed script under test runs here for real."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.history: list[str] = []

    def _env(self, extra: dict[str, str] | None) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(self._root)
        env["PATH"] = f"{self._root / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        if extra:
            env.update(extra)
        return env

    async def run(
        self,
        cmd: str,
        timeout: int = 30,
        envs: dict[str, str] | None = None,
        user: str | None = None,
    ) -> SimpleNamespace:
        del user
        rewritten = cmd.replace("/workspace", str(self._root))
        self.history.append(rewritten)
        proc = await asyncio.to_thread(
            subprocess.run,
            ["bash", "-c", rewritten],
            capture_output=True,
            text=True,
            env=self._env(envs),
            timeout=timeout,
            cwd=str(self._root),
        )
        if proc.returncode != 0:
            raise CommandExitException(
                stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode, error=None
            )
        return SimpleNamespace(exit_code=0, stdout=proc.stdout, stderr=proc.stderr)


class FakeAsyncSandbox:
    """Drop-in for the AsyncSandbox surface the lab tools touch.

    Owns a temp dir (``root``) standing in for /workspace. ``create`` /
    ``connect`` mirror the SDK classmethods so lifecycle-level tests can reuse
    this harness; ``connect`` returns the registered instance for a known id.
    """

    _instances: ClassVar[dict[str, FakeAsyncSandbox]] = {}

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(tempfile.mkdtemp(prefix="fake-sbx-"))
        self.sandbox_id = f"fake-sbx-{uuid4().hex[:8]}"
        self.commands = _FakeCommands(self.root)
        self.files = _FakeFiles(self.root)
        self._install_cli_shims()

    def _install_cli_shims(self) -> None:
        """Install dummy claude/opencode shims so the seed's install lines stay offline."""
        bindir = self.root / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        for name in ("claude", "opencode"):
            shim = bindir / name
            shim.write_text("#!/bin/sh\nexit 0\n")
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    async def is_running(self, **kwargs: Any) -> bool:
        del kwargs
        return True

    async def beta_pause(self) -> None:
        pass

    async def set_timeout(self, **kwargs: Any) -> None:
        del kwargs

    async def kill(self) -> None:
        pass

    @classmethod
    async def create(cls, **kwargs: Any) -> FakeAsyncSandbox:
        del kwargs
        inst = cls()
        cls._instances[inst.sandbox_id] = inst
        return inst

    @classmethod
    async def connect(cls, sandbox_id: str, **kwargs: Any) -> FakeAsyncSandbox:
        del kwargs
        if sandbox_id in cls._instances:
            return cls._instances[sandbox_id]
        inst = cls()
        inst.sandbox_id = sandbox_id
        cls._instances[sandbox_id] = inst
        return inst
