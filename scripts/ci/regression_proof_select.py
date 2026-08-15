#!/usr/bin/env python3
"""Select the regression-marked tests a PR introduces.

Reads pairs of (test file in the PR, same file at the base revision — or a
missing path when the file is new) and prints one pytest node id per line for
every `@pytest.mark.regression` test function present in the PR copy but absent
from the base copy. Only those must go red on base: a marked test whose fix
already merged is green on base by design and proves nothing about this PR.

Usage:
    regression_proof_select.py <pr_file> <base_file> [<pr_file> <base_file> ...]
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

REGRESSION_MARK = "regression"


def _is_regression_mark(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == REGRESSION_MARK


def _test_ids(source: str, *, marked_only: bool) -> set[str]:
    ids: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef | ast.Module):
            continue
        prefix = f"{node.name}::" if isinstance(node, ast.ClassDef) else ""
        for child in node.body:
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not child.name.startswith("test_"):
                continue
            if marked_only and not any(_is_regression_mark(d) for d in child.decorator_list):
                continue
            ids.add(f"{prefix}{child.name}")
    return ids


def main() -> int:
    args = sys.argv[1:]
    if not args or len(args) % 2:
        print("usage: regression_proof_select.py <pr_file> <base_file> ...", file=sys.stderr)
        return 2
    for pr_file, base_file in zip(args[::2], args[1::2], strict=True):
        pr_path, base_path = Path(pr_file), Path(base_file)
        marked = _test_ids(pr_path.read_text(), marked_only=True)
        existing = (
            _test_ids(base_path.read_text(), marked_only=False) if base_path.exists() else set()
        )
        for test_id in sorted(marked - existing):
            print(f"{pr_file}::{test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
