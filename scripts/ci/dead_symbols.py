#!/usr/bin/env python3
"""Report module-level names that nothing in the repo references.

Vulture's enforced set drops "unused variable", so a dead module constant (or
a forgotten type alias) is invisible: the gate says "No unused code found"
while `PLANS_CACHE_KEYS`-style leftovers accumulate. This check is deliberately
narrow and unambiguous: it only reports a top-level assignment whose name
appears nowhere but its own definition, so there is no false positive to
allowlist and no judgement call about dynamic use.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess

SKIP_PARTS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".nx",
    ".git",
    ".claude",
    ".agents",
    "mutants",
    "verify-logs",
}
SKIP_NAMES = {"__all__"}


def _python_files(root: Path) -> list[Path]:
    """Tracked Python files, or a pruned walk outside git.

    `.claude/worktrees/` holds whole repo copies; counting their copies of a
    name would make a dead symbol look referenced.
    """
    if (root / ".git").exists():
        out = subprocess.check_output(
            ["git", "ls-files", "*.py"], cwd=root, text=True, stderr=subprocess.DEVNULL
        )
        return [root / line for line in out.splitlines() if line]
    return [
        path
        for path in root.rglob("*.py")
        if not SKIP_PARTS.intersection(path.parts) and path.name != "conftest.py"
    ]


def _top_level_names(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text())
    names: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id not in SKIP_NAMES:
                names.append((target.id, node.lineno))
    return names


def zero_ref_symbols(app_dir: Path, repo_root: Path) -> list[tuple[Path, str, int]]:
    """Return (file, name, line) for top-level names with no reference anywhere else."""
    occurrences: dict[str, int] = {}
    word = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    for path in _python_files(repo_root):
        for token in word.findall(path.read_text()):
            occurrences[token] = occurrences.get(token, 0) + 1

    findings: list[tuple[Path, str, int]] = []
    for path in sorted(app_dir.rglob("*.py")):
        for name, line in _top_level_names(path):
            if occurrences.get(name, 0) <= 1:
                findings.append((path, name, line))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--app-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    app_dir = args.app_dir or args.repo_root / "apps" / "api" / "app"

    findings = zero_ref_symbols(app_dir, args.repo_root)
    for path, name, line in findings:
        try:
            shown = path.relative_to(args.repo_root)
        except ValueError:
            shown = path
        print(f"{shown}:{line}: top-level name {name} has no reference outside its definition")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
