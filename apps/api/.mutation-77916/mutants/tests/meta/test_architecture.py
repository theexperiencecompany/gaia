"""Meta-tests: import fences and architecture invariants.

These are regression fences for the repo's own rules — the same invariants the
custom AST lints (tools/lints/) enforce, but as tests that fail loud on any
violation. Mirrors OpenClaw's repo-scanning invariant tests (git ls-files +
regex over import specifiers, assert offenders == []).
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
import subprocess

os.environ.setdefault("ENV", "development")

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parents[3] / "app"


def _git_tracked_py_files() -> list[Path]:
    """All app/**/*.py files tracked by git (never os.walk — untracked
    experiments must not change what's asserted)."""
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    out = subprocess.check_output(["git", "ls-files", "apps/api/app"], text=True)
    return [root / p for p in out.splitlines() if p.endswith(".py")]


def test_every_app_module_imports_cleanly() -> None:
    """Every production module under app/ imports without error (Haystack's
    test_imports pattern) — catches circular-import and import-side-effect
    regressions in seconds."""
    failures: list[str] = []
    for path in _git_tracked_py_files():
        rel = path.relative_to(APP_DIR.parents[1])  # repo/apps/api
        rel = rel.with_suffix("")
        parts = list(rel.parts)
        parts[0] = "app"  # normalize to the app package root
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


def test_repository_boundaries() -> None:
    """Only the repository layer may reach MongoDB collections directly.

    Services/endpoints/agents must go through app.db.repositories (the
    repository-boundaries rule, also enforced by tools/lints)."""
    offenders: list[str] = []
    pattern = (
        r"from app\.db\.mongodb\.collections import"
        r"|import app\.db\.mongodb\.collections"
        r"|from app\.db\.mongodb import collections"
    )
    import re

    for path in _git_tracked_py_files():
        path.relative_to(path.anchor)
        text = path.read_text()
        if "app/db/" in str(path):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, "repository-boundary violations:\n" + "\n".join(offenders[:20])


def test_no_stateful_service_classes() -> None:
    """No *Service class may have instance state or non-static methods (the
    no-service-classes rule — services are module-level functions)."""
    import re

    allowlist = {
        "ComposioService",
        "DodoPaymentService",
        "PaymentWebhookService",
        "NotificationService",
        "DeviceTokenService",
        "GaiaKnowledgeService",
    }
    offenders: list[str] = []
    for path in _git_tracked_py_files():
        if "app/services/" not in str(path):
            continue
        text = path.read_text()
        for m in re.finditer(r"^class (\w*Service)\b", text, re.M):
            name = m.group(1)
            if name in allowlist:
                continue
            cls_body = text[m.end() :]
            if re.search(r"def __init__\(self|def \w+\(self", cls_body.split("\n\n")[0]):
                # crude body slice: flag any instance method below the class line
                body = (
                    text[m.end() : text.find("\nclass ", m.end())]
                    if "\nclass " in text[m.end() :]
                    else text[m.end() :]
                )
                if re.search(r"(?:async )?def \w+\(self", body) and not re.search(
                    r"@(?:staticmethod|classmethod)", body
                ):
                    offenders.append(f"{path}: class {name}")
    assert not offenders, "stateful service classes:\n" + "\n".join(offenders[:20])
