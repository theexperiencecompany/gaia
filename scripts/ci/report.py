#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["defusedxml==0.7.1"]
# ///
"""report.py — turning what a run produced into a verdict a reader can act on.

Every subcommand here takes raw output from something else — a diff, a JUnit
report, a linter's stdout, a job's step outcomes — and answers one question
about it, loudly, with the exact reason on failure.

Subcommands:
    regression-proof-select <pr_file> <base_file> [<pr_file> <base_file> ...]
        Print one pytest node id per line for every `@pytest.mark.regression`
        test the PR ADDS. Driven by `pytest.sh regression-proof`.
    regression-proof-verdict <junit.xml>
        Decide whether the base-revision run actually proved anything: every
        regression test must have FAILED, not passed and not merely errored.
    annotations
        Read mypy/tsc/ruff/biome output on stdin and re-emit it as
        `::error file=,line=` GitHub annotations.
    step-outcomes <name>=<outcome> [...]
        Fail a job when any of its `continue-on-error` steps did not pass,
        naming every one that did not.

Interpreters: `regression-proof-verdict` needs defusedxml and is invoked with
`uv run --no-project` (the PEP 723 block above is what supplies it); the other
three are stdlib-only and run under a plain `python3` / the suite's venv. That
is why defusedxml is imported inside its own subcommand rather than at module
level — a top-level import would break every plain-`python3` invocation.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import re
import sys

# ---------------------------------------------------------------------------
# regression-proof-select
#
# Reads pairs of (test file in the PR, same file at the base revision — or a
# missing path when the file is new) and prints one pytest node id per line for
# every `@pytest.mark.regression` test function present in the PR copy but
# absent from the base copy. Only those must go red on base: a marked test whose
# fix already merged is green on base by design and proves nothing about this PR.
# ---------------------------------------------------------------------------

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


def cmd_regression_proof_select(args: list[str]) -> int:
    if not args or len(args) % 2:
        print(
            "usage: report.py regression-proof-select <pr_file> <base_file> ...",
            file=sys.stderr,
        )
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


# ---------------------------------------------------------------------------
# regression-proof-verdict
#
# Reads the JUnit XML of the base-revision run (see `pytest.sh regression-proof`)
# and applies one rule per `@pytest.mark.regression` test:
#
#     it must FAIL — an assertion that goes red without the fix.
#
# PASSED is the obvious rejection: a test green on base does not pin the bug it
# claims to. ERROR-only is rejected too, and that is the subtler half. An error
# is a test that never reached its assertions — a missing fixture, an import of
# a symbol the base does not have, a service that would not start. It looks like
# proof in a summary line ("did not pass") while proving nothing about the bug,
# which is exactly how this gate spent its life reporting success it had not
# earned. A test that both fails and then errors in teardown is fine: the
# assertion still ran.
# ---------------------------------------------------------------------------


def cmd_regression_proof_verdict(args: list[str]) -> int:
    """Exit 0 when every regression test failed on base, 1 otherwise."""
    # Imported here, not at module level: this is the only subcommand that needs
    # a third-party parser, and it is the only one invoked through
    # `uv run --no-project` (which resolves the PEP 723 block above). The other
    # subcommands run under a plain python3 that has no defusedxml.
    from defusedxml.ElementTree import parse as parse_xml

    if len(args) != 1:
        print("usage: report.py regression-proof-verdict <junit.xml>", file=sys.stderr)
        return 2
    try:
        root = parse_xml(args[0]).getroot()
    except OSError as exc:
        print(f"ERROR: regression-proof — cannot read the JUnit report: {exc}", file=sys.stderr)
        return 1

    # One test can emit several <testcase> entries (call + teardown), so fold
    # them together and ask what happened across all of them.
    failed: dict[str, bool] = defaultdict(bool)
    errored: dict[str, bool] = defaultdict(bool)
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}::{case.get('name', '')}".lstrip(":")
        failed[name] |= case.find("failure") is not None
        errored[name] |= case.find("error") is not None

    if not failed:
        print("ERROR: regression-proof — the JUnit report lists no tests at all.")
        print("       The run did not execute; that is a failure, not a pass.")
        return 1

    passed_on_base = sorted(n for n in failed if not failed[n] and not errored[n])
    errored_only = sorted(n for n in failed if errored[n] and not failed[n])
    proven = sorted(n for n in failed if failed[n])

    if passed_on_base:
        print(f"ERROR: regression-proof — {len(passed_on_base)} test(s) PASS on base:")
        for name in passed_on_base:
            print(f"  {name}")
        print("       A regression test must go red without its fix. Either the fix is")
        print("       not needed, or the test does not exercise the bug it names.")
        return 1

    if errored_only:
        print(f"ERROR: regression-proof — {len(errored_only)} test(s) ERRORED on base:")
        for name in errored_only:
            print(f"  {name}")
        print("       An error is not proof: the test never reached its assertions, so")
        print("       it shows the harness broke, not that the bug is caught. Make it")
        print("       runnable against the base revision — assert on behavior rather")
        print("       than importing symbols the fix introduces.")
        return 1

    print(f"regression-proof: {len(proven)} regression test(s) fail on base as required")
    for name in proven:
        print(f"  FAILED {name}")
    return 0


# ---------------------------------------------------------------------------
# annotations
#
# Convert mypy/tsc/ruff/biome output to ::error file,line annotations.
# ---------------------------------------------------------------------------

ANNOTATION_PATTERNS = [
    # mypy: path:line: error: msg  or path:line:col: error
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)?\s*(?:error|warning):"),
    # tsc: path(line,col): error TS...
    re.compile(r"^(?P<file>[^\(]+)\((?P<line>\d+),(?P<col>\d+)\):\s*error"),
    # ruff concise: path:line:col: CODE msg
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\d+:\s*[A-Z]+\d+\s"),
    # biome concise: path:line:col lint/category
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)\s"),
]


def cmd_annotations(args: list[str]) -> int:
    if args:
        print("usage: report.py annotations  (reads the tool output on stdin)", file=sys.stderr)
        return 2
    for line in sys.stdin:
        for pattern in ANNOTATION_PATTERNS:
            match = pattern.match(line.strip())
            if match:
                path = match.group("file").strip()
                line_no = match.group("line")
                print(f"::error file={path},line={line_no}::{line.strip()[:500]}")
                break
    return 0


# ---------------------------------------------------------------------------
# step-outcomes
#
# A job that runs several independent tools (see code-quality.yml's
# python-static lane) marks each tool step `continue-on-error: true` so one red
# tool does not hide the rest, then calls this with one "<name>=<outcome>" pair
# per step. Outcome values are GitHub's own step outcomes: success, failure,
# cancelled, skipped.
# ---------------------------------------------------------------------------


def cmd_step_outcomes(args: list[str]) -> int:
    if not args:
        print('usage: report.py step-outcomes "ruff=success" "bandit=failure" ...', file=sys.stderr)
        return 2

    failed = 0
    for pair in args:
        name, _, outcome = pair.partition("=")
        print(f"  {name + ':':<16} {outcome}")
        if outcome != "success":
            print(f"::error::{name} did not pass (outcome: {outcome})")
            failed += 1

    if failed:
        print(f"::error::{failed} of {len(args)} step(s) failed — expand the groups above for each")
        return 1
    print(f"All {len(args)} steps passed")
    return 0


SUBCOMMANDS = {
    "regression-proof-select": cmd_regression_proof_select,
    "regression-proof-verdict": cmd_regression_proof_verdict,
    "annotations": cmd_annotations,
    "step-outcomes": cmd_step_outcomes,
}


def main() -> int:
    argv = sys.argv[1:]
    sub = argv[0] if argv else ""
    handler = SUBCOMMANDS.get(sub)
    if handler is None:
        print(f"report.py: unknown subcommand '{sub}'", file=sys.stderr)
        print(f"usage: report.py <{' | '.join(SUBCOMMANDS)}> [args]", file=sys.stderr)
        return 2
    return handler(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
