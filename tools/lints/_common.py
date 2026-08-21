"""Shared plumbing for the custom Python AST lints.

Each rule module exposes module-level ``RULE`` / ``WHY`` / ``DOC`` strings and a
``check(files: list[Path]) -> list[Violation]`` function. The runner
(``run.py``) discovers the Python files once, hands the same list to every rule,
and each rule filters down to the tree it governs. Stdlib only — no app imports,
no third-party deps — so the checks stay fast and runnable on a bare CI runner.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

# Directory/segment names that never contain enforceable app code.
_SKIP_SEGMENTS = ("__pycache__", "/tests/", "/migrations/", "/alembic/", "/.venv/")


@dataclass(frozen=True)
class Violation:
    """One rule failure, carrying everything the teaching message needs."""

    path: Path
    line: int
    detail: str  # what is wrong at this exact spot
    fix: str  # the concrete remediation for this offender


def iter_python_files(paths: list[Path]) -> list[Path]:
    """Expand the given paths to real, non-test ``.py`` files, sorted."""
    out: set[Path] = set()
    for raw in paths:
        p = raw.resolve()
        candidates = p.rglob("*.py") if p.is_dir() else ([p] if p.suffix == ".py" else [])
        for f in candidates:
            posix = f.as_posix()
            if any(seg in posix for seg in _SKIP_SEGMENTS):
                continue
            if f.name.startswith("test_") or f.name.endswith("_test.py"):
                continue
            out.add(f)
    return sorted(out)


def display(path: Path) -> str:
    """Path relative to CWD when possible (keeps ``file:line`` clickable)."""
    try:
        return os.path.relpath(path, Path.cwd())
    except ValueError:
        return str(path)


def report_rule(rule: str, why: str, doc: str, violations: list[Violation]) -> None:
    """Print one rule's failures in the shared teaching format, to stderr.

    Used by the AST-rule runner and by the standalone config checks alike, so
    every custom lint fails looking the same way.
    """
    print(f"\n✗ {rule} — {len(violations)} violation(s)", file=sys.stderr)
    print(f"  why:  {why}", file=sys.stderr)
    print(f"  docs: {doc}", file=sys.stderr)
    for v in violations:
        print(f"  {display(v.path)}:{v.line}  {v.detail}", file=sys.stderr)
        print(f"      fix: {v.fix}", file=sys.stderr)
        # GitHub annotation — surfaces as inline file,line error in the PR diff.
        print(
            f"::error file={display(v.path)},line={v.line}::{rule}: {v.detail} — fix: {v.fix}",
            file=sys.stderr,
        )
