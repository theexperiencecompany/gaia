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
from pathlib import Path
import sys

TESTS_DIR = Path("apps/api/tests")


def _module_refs(path: Path) -> set[str]:
    """Every app.* dotted name a test file mentions (imports + string literals).

    String literals must be BARE module paths: a real patch target is
    ``"app.x.y.z"``, while fixture content embedding a module name inside
    quotes/parens (``'patch("app.x.y.z", ...)'``) is a test-data string, not
    a reference — matching it would pull in test files that never exercise
    the module.
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
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            candidate = node.value.strip()
            if _is_bare_module_path(candidate):
                refs.add(candidate)
    return refs


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
        refs = _module_refs(path)
        # Match the module exactly or as a prefix — patch targets routinely
        # carry a function suffix (app.x.y.module.get_conversations).
        if module in refs or module_py in refs:
            hits.append(str(path))
            continue
        if any(ref.startswith(f"{module}.") for ref in refs):
            hits.append(str(path))
    hits.sort(key=lambda p: (not p.startswith(str(tests_dir / "unit")), p))
    return hits


def main() -> int:
    changed = [line.strip() for line in sys.stdin if line.strip()]
    matrix: list[dict[str, str]] = []
    failures: list[str] = []
    for module in changed:
        rel = module.removeprefix("apps/api/")
        rel_py = rel.removeprefix("app/")
        rel_py = rel_py.removesuffix(".py")
        unit_mirror = f"tests/unit/{Path(rel_py).parent}/test_{Path(rel_py).stem}.py"
        if (TESTS_DIR.parent / unit_mirror).exists():
            matrix.append({"module": rel, "testfile": unit_mirror})
            continue
        hits = _test_files_for(rel_py)
        if hits:
            matrix.append({"module": rel, "testfile": hits[0].removeprefix("apps/api/")})
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


if __name__ == "__main__":
    raise SystemExit(main())
