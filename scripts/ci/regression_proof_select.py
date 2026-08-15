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


def _is_regression_mark(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr == REGRESSION_MARK


def _mentions_regression_mark(node: ast.AST) -> bool:
    return any(_is_regression_mark(sub) for sub in ast.walk(node) if isinstance(sub, ast.expr))


def _pytestmark_is_regression(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            if _mentions_regression_mark(stmt.value):
                return True
    return False


def _test_ids(source: str, *, marked_only: bool) -> set[str]:
    """Test node ids in ``source``; with ``marked_only`` just those carrying the
    regression mark — on the function, on its class, on the module's
    ``pytestmark``, or on one of its ``pytest.param`` cases (pytest's ``-m``
    then narrows the run to the marked cases)."""
    tree = ast.parse(source)
    module_marked = _pytestmark_is_regression(tree.body)
    ids: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.Module):
            continue
        prefix = f"{node.name}::" if isinstance(node, ast.ClassDef) else ""
        scope_marked = module_marked or (
            isinstance(node, ast.ClassDef)
            and (
                any(_is_regression_mark(d) for d in node.decorator_list)
                or _pytestmark_is_regression(node.body)
            )
        )
        for child in node.body:
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not child.name.startswith("test_"):
                continue
            if marked_only and not (
                scope_marked or any(_mentions_regression_mark(d) for d in child.decorator_list)
            ):
                continue
            ids.add(f"{prefix}{child.name}")
    return ids


def _mark_present_in_text(source: str) -> bool:
    return f"mark.{REGRESSION_MARK}" in source


def main() -> int:
    args = sys.argv[1:]
    if not args or len(args) % 2:
        print("usage: regression_proof_select.py <pr_file> <base_file> ...", file=sys.stderr)
        return 2
    for pr_file, base_file in zip(args[::2], args[1::2], strict=True):
        pr_path, base_path = Path(pr_file), Path(base_file)
        pr_source = pr_path.read_text()
        marked = _test_ids(pr_source, marked_only=True)
        if _mark_present_in_text(pr_source) and not marked:
            print(
                f"ERROR: regression-proof — {pr_file} mentions pytest.mark.{REGRESSION_MARK} but no "
                "test could be attributed to it (unsupported placement). Put the mark on the test "
                "function, its class, the module's pytestmark, or a pytest.param case.",
                file=sys.stderr,
            )
            return 1
        existing = (
            _test_ids(base_path.read_text(), marked_only=False) if base_path.exists() else set()
        )
        for test_id in sorted(marked - existing):
            print(f"{pr_file}::{test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
