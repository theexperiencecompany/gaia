#!/usr/bin/env python3
"""Emit the mutation-check matrix: changed app modules + their test files.

Reference detection is AST-based because grep misses this codebase's two
common reference forms: `from app.x.endpoints import y` (submodule imported
from its package) and mock patch targets written as strings
(`"app.agents.tools.integrations.google_meet_tool"`). A module is "covered"
when any test file imports it, imports from it, or names it in a string
literal (patch target).

Input:  changed app module paths on stdin (one per line, repo-root-relative).
Output: {"modules": [{"module": ..., "testfile": ...}, ...]}
Exit 1 with a ::error message when a changed module has no test file.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

APP_DIR = Path("apps/api/app")
TESTS_DIR = Path("apps/api/tests")


def _module_refs(path: Path) -> set[str]:
    """Every app.* dotted name a test file references.

    Two reference forms are trusted:
    - import statements (import X / from X import Y)
    - bare module-path strings used as call arguments (patch targets) or
      assignment values (module-path constants like CONV_SERVICE = "app...").
    Bare strings in ANY other position (assert operands, docstrings, fixture
    data) are not references — matching them pulls in test files that never
    exercise the module (the detector's own unit test poisoned the matrix
    this way twice).
    """
    refs: set[str] = set()
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return refs
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            refs.add(node.module)
            for alias in node.names:
                refs.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Call):
            for arg in node.args:
                _collect_module_strings(refs, arg)
            for keyword in node.keywords:
                _collect_module_strings(refs, keyword.value)
        elif isinstance(node, ast.Assign):
            _collect_module_strings(refs, node.value)
    return refs


def _collect_module_strings(refs: set[str], node: ast.AST) -> None:
    """Add bare module-path strings from call args / assignment values.

    Recurses through list/tuple literals (parametrize argument lists hold
    patch targets as tuples).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        candidate = node.value.strip()
        if _is_bare_module_path(candidate):
            refs.add(candidate)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            _collect_module_strings(refs, element)


def _is_bare_module_path(candidate: str) -> bool:
    """True for ``app.some.module`` / ``app.some.module.thing`` and nothing else.

    Rejects strings that embed a module name in surrounding syntax (quotes,
    parens, spaces) — those are fixture data, not references.
    """
    if not candidate.startswith("app."):
        return False
    if any(char in candidate for char in "\"'(), "):
        return False
    return all(part.isidentifier() for part in candidate.split("."))


def _matches(module: str, module_py: str, refs: set[str]) -> bool:
    """Whether ``refs`` reference ``module`` exactly or as a prefix."""
    return module in refs or module_py in refs or any(ref.startswith(f"{module}.") for ref in refs)


def _importers_of(module: str) -> list[str]:
    """App modules that import ``module`` (one level of consumer following)."""
    module_py = f"{module}.py"
    importers: set[str] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        if _matches(module, module_py, _module_refs(path)):
            relative = path.relative_to(APP_DIR).with_suffix("")
            importers.add(f"app.{relative.as_posix().replace('/', '.')}")
    return sorted(importers)


def _test_files_for(module_rel: str, tests_dir: Path = TESTS_DIR) -> list[str]:
    """Test files (repo-root-relative) referencing the module, unit tier first.

    Real-tier suites (tests/integration/real/...) skip without
    USE_REAL_SERVICES=1, which would leave the mutation run with zero
    covering tests; prefer hermetic tests/unit/ hits so the lane can
    actually exercise the module.
    """
    module = f"app.{module_rel.replace('/', '.')}"
    module_py = f"{module}.py"
    hits: list[str] = []
    for path in sorted(tests_dir.rglob("*.py")):
        # Only actual test files qualify: conftest.py defines fixtures and
        # helper modules (store.py, llm.py, ...) support them — running one
        # as the module's test file would prove nothing and mask the real
        # gap.
        if not path.name.startswith("test_"):
            continue
        refs = _module_refs(path)
        # Match the module exactly or as a prefix — patch targets routinely
        # carry a function suffix (app.x.y.module.get_conversations).
        if _matches(module, module_py, refs):
            hits.append(str(path))
    if not hits:
        # No test references the module directly — follow its CONSUMERS one
        # level: modules that import it exercise it, so their test files
        # cover it. (app.memory.chroma_store is only reached through
        # app.memory.engine, whose real-tier tests drive every store line.)
        consumers = _importers_of(module)
        for consumer in consumers:
            hits.extend(_test_files_for(consumer.replace("app.", "", 1), tests_dir))
    hits.sort(key=lambda p: (not p.startswith(str(tests_dir / "unit")), p))
    return hits


def main() -> int:
    changed = [line.strip() for line in sys.stdin if line.strip()]
    matrix: list[dict[str, object]] = []
    failures: list[str] = []
    for module in changed:
        rel = module.removeprefix("apps/api/")
        rel_py = rel.removeprefix("app/")
        rel_py = rel_py.removesuffix(".py")
        unit_mirror = f"tests/unit/{Path(rel_py).parent}/test_{Path(rel_py).stem}.py"
        if (TESTS_DIR.parent / unit_mirror).exists():
            matrix.append(_entry(rel, unit_mirror))
            continue
        hits = _test_files_for(rel_py)
        if hits:
            matrix.append(_entry(rel, hits[0].removeprefix("apps/api/")))
            continue
        failures.append(
            f"changed module {rel} has no test file anywhere (looked for {unit_mirror} "
            "and AST importers/patch targets). Changed code must ship tests."
        )
    if failures:
        for failure in failures:
            print(f"::error::mutation gate: {failure}", file=sys.stderr)
        return 1
    print(json.dumps(matrix))
    return 0


def _entry(module_rel: str, testfile: str) -> dict[str, object]:
    """Module matrix entry with the PR's changed line ranges for this file.

    The gate is diff-driven: a survivor only fails the lane when its mutation
    lands on a line the PR changed. Mutants on untouched lines are noted, not
    failures — otherwise a 1-line import fix would demand full-module test
    coverage.
    """
    ranges = _changed_line_ranges(f"apps/api/{module_rel}")
    return {"module": module_rel, "testfile": testfile, "changed_lines": ranges}


def _changed_line_ranges(path: str) -> list[list[int]]:
    """PR-changed line ranges for a file, from the merge-base diff (unified=0).

    Returns [] when GITHUB_BASE_REF is unset (local runs). In CI the diff
    MUST succeed — empty ranges would silently pass every survivor, so a
    git failure there is a hard lane error.
    """
    base = os.environ.get("GITHUB_BASE_REF", "")
    if not base:
        return []
    try:
        out = subprocess.check_output(
            ["git", "diff", "--unified=0", f"origin/{base}...HEAD", "--", path],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"::error::mutation gate: could not diff {path} against origin/{base}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    ranges: list[list[int]] = []
    for line in out.splitlines():
        if not line.startswith("@@"):
            continue
        match = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        ranges.append([start, start + max(count, 1) - 1])
    return ranges


if __name__ == "__main__":
    raise SystemExit(main())
