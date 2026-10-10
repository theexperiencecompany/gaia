"""Shared plumbing for the custom Python AST lints.

Each rule module exposes module-level ``RULE`` / ``WHY`` / ``DOC`` strings and a
``check(files: list[Path]) -> list[Violation]`` function. The runner
(``run.py``) discovers the Python files once, hands the same list to every rule,
and each rule filters down to the tree it governs. Stdlib only — no app imports,
no third-party deps — so the checks stay fast and runnable on a bare CI runner.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import tomllib

# Directory/segment names that never contain enforceable app code.
_SKIP_SEGMENTS = ("__pycache__", "/tests/", "/migrations/", "/alembic/", "/.venv/")


@dataclass(frozen=True)
class Violation:
    """One rule failure, carrying everything the teaching message needs."""

    path: Path
    line: int
    detail: str  # what is wrong at this exact spot
    fix: str  # the concrete remediation for this offender


def iter_python_files(paths: list[Path], *, include_tests: bool = False) -> list[Path]:
    """Expand the given paths to real ``.py`` files, sorted; tests only on request."""
    skip = tuple(seg for seg in _SKIP_SEGMENTS if include_tests is False or seg != "/tests/")
    out: set[Path] = set()
    for raw in paths:
        p = raw.resolve()
        candidates = p.rglob("*.py") if p.is_dir() else ([p] if p.suffix == ".py" else [])
        for f in candidates:
            posix = f.as_posix()
            if any(seg in posix for seg in skip):
                continue
            if not include_tests and (f.name.startswith("test_") or f.name.endswith("_test.py")):
                continue
            out.add(f)
    return sorted(out)


def find_repo_root(files: Sequence[Path]) -> Path | None:
    """Walk up from the first scanned file to the nearest ancestor whose pyproject.toml configures ruff.

    A pyproject.toml with no ``[tool.ruff]`` table (this repo's own
    apps/api/pyproject.toml, which carries only uv/mypy/coverage config) is
    not ruff's project root -- matches ruff's own discovery, which keeps
    walking up past a config file that does not configure it.
    """
    if not files:
        return None
    for candidate in files[0].resolve().parents:
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            continue
        if "ruff" in data.get("tool", {}):
            return candidate
    return None


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a ruff/globset-style glob (``*``, ``**``, ``?``, ``[...]``) to an anchored regex.

    No ``!`` negation support -- this repo's per-file-ignores never use it.
    """
    parts: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i)
            if end == -1:
                parts.append(re.escape(pattern[i]))
                i += 1
            else:
                parts.append(pattern[i : end + 1])
                i = end + 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile(f"^{''.join(parts)}$")


def ruff_exempt_files(files: Sequence[Path], code: str, repo_root: Path | None) -> frozenset[Path]:
    """Return the ``files`` root pyproject.toml already exempts from ``code`` via per-file-ignores.

    Mirrors ruff's own matching (docs.astral.sh/ruff/settings/#per-file-ignores):
    a pattern containing ``/`` is matched against the file's path relative to
    ``repo_root``; a bare pattern (no ``/``) matches the file's basename
    anywhere in the tree, per ruff's documented single-path-pattern rule.
    """
    if repo_root is None:
        return frozenset()
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return frozenset()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    entries = data.get("tool", {}).get("ruff", {}).get("lint", {}).get("per-file-ignores", {})
    patterns = [
        (pattern, _glob_to_regex(pattern))
        for pattern, codes in entries.items()
        if isinstance(codes, list) and code in codes
    ]
    if not patterns:
        return frozenset()
    exempt: set[Path] = set()
    for f in files:
        resolved = f.resolve()
        try:
            rel = resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        for pattern, regex in patterns:
            target = resolved.name if "/" not in pattern else rel
            if regex.match(target):
                exempt.add(f)
                break
    return frozenset(exempt)


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
