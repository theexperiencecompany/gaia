"""Meta-tests: import fences and architecture invariants.

Regression fences for invariants no custom AST lint (tools/lints/) covers;
the lints own repository boundaries and service classes. Mirrors OpenClaw's
repo-scanning invariant tests (git ls-files, assert offenders == []).
"""

from __future__ import annotations

import ast
import importlib
import logging
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("ENV", "development")

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parents[2] / "app"


def _git_tracked_py_files() -> list[Path]:
    """Return all app/**/*.py files tracked by git (never os.walk — untracked experiments must not change what's asserted)."""
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    out = subprocess.check_output(["git", "ls-files", "apps/api/app"], cwd=root, text=True)
    return [root / p for p in out.splitlines() if p.endswith(".py")]


def test_every_app_module_imports_cleanly() -> None:
    """Every production module under app/ imports without error (Haystack's test_imports pattern)."""
    failures: list[str] = []
    for path in _git_tracked_py_files():
        parts = path.relative_to(APP_DIR.parent).with_suffix("").parts
        # Sandbox assets (skill templates under hyphenated dirs) are files, not modules.
        if not all(part.isidentifier() for part in parts):
            continue
        module = ".".join(parts)
        if module.split(".")[-1] == "__init__":
            continue
        try:
            importlib.import_module(module)
        except Exception as exc:
            # The assertion message carries only the exception summary; a
            # circular-import chain is unreadable without the frames, so the
            # full traceback goes to the captured log pytest prints on failure.
            logger.exception("module failed to import: %s", module)
            failures.append(f"{module}: {type(exc).__name__}: {exc}")
    assert not failures, "import failures:\n" + "\n".join(failures[:30])


def test_the_embedding_sidecar_imports_without_settings() -> None:
    """The sidecar boots with no API secrets, so its import graph must not reach settings."""
    result = subprocess.run(
        [sys.executable, "-c", "import app.services.embedding_sidecar.server"],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        env={"ENV": "test", "PATH": os.environ["PATH"], "LOG_LEVEL": "ERROR"},
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_the_configurable_key_matches_langgraphs() -> None:
    """app.models.agent_config spells langgraph's CONF out to stay a leaf."""
    from langgraph.constants import CONF

    from app.models.agent_config import CONFIGURABLE_KEY

    assert CONFIGURABLE_KEY == CONF


def _calls(path: Path) -> list[ast.Call]:
    return [node for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Call)]


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _is_attribute_call(call: ast.Call, owner: str, attr: str) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == attr
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == owner
    )


def test_thread_pools_carry_the_callers_context() -> None:
    """Every app thread pool is ContextThreadPoolExecutor: a plain pool drops the Composio account scope."""
    offenders = [
        f"{path}:{call.lineno}"
        for path in _git_tracked_py_files()
        if not str(path).endswith("app/utils/concurrency.py")
        for call in _calls(path)
        if _call_name(call) == "ThreadPoolExecutor"
    ]
    assert not offenders, "use app.utils.concurrency.ContextThreadPoolExecutor:\n" + "\n".join(
        offenders
    )


def test_every_composio_call_names_its_account() -> None:
    """execute_request and a bare tools.proxy carry no account; tools.execute must name or pin one."""
    offenders: list[str] = []
    for path in _git_tracked_py_files():
        for call in _calls(path):
            keywords = {k.arg for k in call.keywords}
            unscoped = (
                (isinstance(call.func, ast.Name) and call.func.id == "execute_request")
                or (
                    _is_attribute_call(call, "tools", "proxy")
                    and not str(path).endswith("app/services/composio/proxy_client.py")
                )
                or (
                    _is_attribute_call(call, "tools", "execute")
                    and not keywords & {"connected_account_id", "modifiers"}
                )
            )
            if unscoped:
                offenders.append(f"{path}:{call.lineno}")
    assert not offenders, "Composio calls with no account:\n" + "\n".join(offenders)
