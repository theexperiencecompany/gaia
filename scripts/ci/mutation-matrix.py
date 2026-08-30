#!/usr/bin/env python3
"""Emit the mutation-check matrix: changed app modules + their test files.

Reference detection is AST-based because grep misses this codebase's two
common reference forms: `from app.x.endpoints import y` (submodule imported
from its package) and mock patch targets written as strings
(`"app.agents.tools.integrations.google_meet_tool"`). A module is "covered"
when any test file imports it, imports from it, or names it in a string
literal (patch target).

Input:  changed app module paths on stdin (one per line, repo-root-relative).
Output: [{"module": ..., "testfiles": [...], "changed_lines": [...]}, ...]
        Every test file referencing the module, not one — see with_unit_mirror.
Exit 1 with a ::error message when a changed module has no test file.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from functools import cache
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tokenize

APP_DIR = Path("apps/api/app")
TESTS_DIR = Path("apps/api/tests")
# The repo has one base branch (CLAUDE.md); local runs diff against it so a
# local mutation run scopes exactly like the PR lane does.
LOCAL_BASE_BRANCH = "master"


def _merge_base() -> str:
    """The merge-base commit between HEAD and the PR's base ref, or "" outside CI.

    The single source of truth both diff-against-base computations in this
    file use (line ranges below, and comment-only detection). Resolving the
    actual merge-base commit — not just ``origin/<base>``'s current tip —
    matters: if the base branch has moved since the PR branched, diffing
    against its tip would pull in unrelated changes landed on the base after
    the branch point and could misjudge a genuine PR change as comment-only
    (or vice versa).

    Outside CI, GITHUB_BASE_REF is unset and we fall back to the repo's single
    base branch. That fallback is load-bearing, not a convenience: an empty
    merge-base yields empty line ranges, and empty ranges classify EVERY
    survivor as out-of-scope, so the run reports "no survivors" and exits 0
    while CI fails the same module. A local gate that cannot fail is worse
    than no local gate, so local resolves a real base like CI does.

    Returns "" only when no base can be resolved at all (a clone with no
    origin and no local master). Callers must treat "" as "scope unknown" and
    refuse to run — never as "nothing changed".
    """
    base = os.environ.get("GITHUB_BASE_REF", "") or LOCAL_BASE_BRANCH
    for ref in (f"origin/{base}", base):
        try:
            return subprocess.check_output(
                ["git", "merge-base", ref, "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            continue
    if os.environ.get("GITHUB_BASE_REF"):
        print(
            f"::error::mutation gate: could not resolve merge-base with origin/{base}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return ""


def _tokens_without_comments(source: str) -> list[tuple[int, str]] | None:
    """``source``'s tokens with COMMENT and NL (comment-only-line terminator)
    stripped, or None if it fails to tokenize.

    Stripping only COMMENT would leave a stray NL where a whole-line comment
    used to be, making a deleted comment-only line look like a structural
    change. Stripping both makes the comparison see straight through both
    forms: a trailing ``# noqa: X`` sliced off a code line, and a whole line
    that was nothing but a comment to begin with.
    """
    tokens: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING):
                continue
            tokens.append((tok.type, tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return tokens


def _is_comment_only_change(module_path: str, merge_base: str) -> bool:
    """True when ``module_path``'s diff against ``merge_base`` changes only
    comments — i.e. it has zero possible mutants, so requiring a test file
    for it would be meaningless.

    A pragmatic line-based diff (skip lines whose changed side starts with
    ``#``) is not enough here: this codebase's suppressions are routinely
    trailing comments on a code line (``except Exception as e:  # noqa:
    BLE001``), and after the comment is deleted the changed line no longer
    starts with ``#`` at all — a line-prefix check would misclassify that as
    a code change. Tokenizing both sides and comparing with COMMENT/NL
    stripped catches both the trailing-comment and whole-line-comment forms
    correctly, because it compares what the code actually *is*, not how the
    diff happens to be shaped.
    """
    try:
        old_source = subprocess.check_output(
            ["git", "show", f"{merge_base}:{module_path}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False  # new file, or base lookup failed — not comment-only
    new_full_path = Path(module_path)
    if not new_full_path.exists():
        return False  # deleted file — not comment-only
    old_tokens = _tokens_without_comments(old_source)
    new_tokens = _tokens_without_comments(new_full_path.read_text())
    if old_tokens is None or new_tokens is None:
        return False  # unparseable on either side — don't guess, enforce normally
    return old_tokens == new_tokens


@cache
def _module_refs(path: Path) -> frozenset[str]:
    """Every app.* dotted name a test file references.

    Memoized, and returning an immutable set so a shared cached value cannot be
    mutated by a caller. Every changed module used to re-parse every test file
    AND (via the consumer fallback) every app file: on a whole-tree diff — 427
    modules against ~1500 files — that is hundreds of thousands of AST parses,
    and the plan step hit the lane's 10-minute ceiling and was cancelled, so
    nothing downstream got a gate at all. Each file is now parsed once.

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
        return frozenset()
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
    return frozenset(refs)


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


def _matches(module: str, module_py: str, refs: frozenset[str]) -> bool:
    """Whether ``refs`` reference ``module`` exactly or as a prefix."""
    return module in refs or module_py in refs or any(ref.startswith(f"{module}.") for ref in refs)


@cache
def _py_files(root: Path) -> tuple[Path, ...]:
    """Sorted *.py under root, walked once — the rglob itself was repeated per module."""
    return tuple(sorted(root.rglob("*.py")))


@cache
def _importers_of(module: str) -> tuple[str, ...]:
    """App modules that import ``module`` (one level of consumer following)."""
    module_py = f"{module}.py"
    importers: set[str] = set()
    for path in _py_files(APP_DIR):
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
    for path in _py_files(tests_dir):
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


def with_unit_mirror(
    module_rel: str, hits: Sequence[str], repo_root: Path = TESTS_DIR.parent
) -> list[str]:
    """Every test file for a module, its unit mirror first — the gate's full set.

    The mirror used to short-circuit the scan instead of joining it: a module
    that had one was measured against ONLY that file, and a module without one
    against whichever hit sorted first. Either way the rest were discarded, so
    mutants covered only by a discarded file were reported as "no covering
    test" — informational, failing nothing. ``app/agents/tools/executor_tool.py``
    is the extreme case: measured against the file the sort picked, all 65 of
    its mutants land in that bucket and the gate reports OK having killed
    nothing; measured against every referencing file, 24 real survivors appear
    on lines the PR changed.
    """
    mirror = f"tests/unit/{Path(module_rel).parent}/test_{Path(module_rel).stem}.py"
    ordered = [hit.removeprefix("apps/api/") for hit in hits]
    # Unit tier only. Every selected file is re-run once PER MUTANT, so an e2e
    # file in this list is paid for tens of times: app/workers/tasks/
    # workflow_tasks.py picked up tests/e2e/test_workflow_execution.py, which
    # compiles real graphs, and the module collapsed from 9.43 to 0.11
    # mutations/second — all 35 mutants hit mutmut's per-mutant timeout and the
    # run proved nothing. This is the instrument's documented scope (see the
    # hermetic-fence note in scripts/test/mutation.sh); the slower tiers are
    # already run properly, once, by test-python.
    #
    # Kept as a filter rather than a cap: dropping the slow tiers is what makes
    # the run finish, and dropping *arbitrary* files is what re-introduces the
    # false-green this function exists to prevent — so every unit file stays.
    unit_only = [hit for hit in ordered if hit.startswith("tests/unit/")]
    # A module whose only coverage is integration/e2e keeps it: measuring it
    # slowly beats not measuring it, and reporting "no test file" would be a lie.
    ordered = unit_only or ordered
    if (repo_root / mirror).exists():
        ordered = [mirror, *(hit for hit in ordered if hit != mirror)]
    return ordered


def scope(module_rel: str) -> int:
    """Print the compact JSON line scope for ONE module, for mutation.sh.

    This is the same computation the matrix does per module, exposed as a CLI
    so the local runner and the CI lane cannot drift into two different ideas
    of "changed". A module with no diff against the base scopes to the WHOLE
    file: running the gate on untouched code is a legitimate thing to ask for,
    and answering it with an empty scope would be the silent pass this exists
    to prevent.
    """
    path = f"apps/api/{module_rel}"
    merge_base = _merge_base()
    if not merge_base:
        print(
            "::error::mutation gate: no base commit to diff against — cannot "
            "determine which lines this change owns",
            file=sys.stderr,
        )
        return 1
    ranges = _changed_line_ranges(path, merge_base)
    if not ranges:
        line_count = len(Path(path).read_text(encoding="utf-8").splitlines())
        print(
            f"mutation: {module_rel} has no diff vs {merge_base[:12]} — "
            f"scoping the whole file ({line_count} lines)",
            file=sys.stderr,
        )
        ranges = [[1, max(line_count, 1)]]
    print(json.dumps(ranges, separators=(",", ":")))
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--scope":
        return scope(sys.argv[2].removeprefix("apps/api/"))
    changed = [line.strip() for line in sys.stdin if line.strip()]
    merge_base = _merge_base()
    matrix: list[dict[str, object]] = []
    failures: list[str] = []
    for module in changed:
        rel = module.removeprefix("apps/api/")
        # A comment-only diff has zero possible mutants — checked before the
        # test-file lookup, and regardless of whether a test file exists.
        # This isn't just about the "no test file" failure: even a module
        # WITH a test file pays a real cost here — mutmut's `# pragma: no
        # mutate` line-scoping only suppresses mutants ON that exact line,
        # so a single-line comment change inside a large, weakly-covered
        # function still leaves the rest of that function's body fully
        # mutable and can run mutmut's full per-mutant test battery across
        # it. That's how a one-line noqa removal produced 157 mutants and
        # blew the per-module timeout in practice. Enforcing test coverage —
        # or even attempting it — for a diff that changed no code proves
        # nothing either way, so skip it before the expensive test-file
        # search and the mutation run even start. Printed, never silent.
        if merge_base and _is_comment_only_change(module, merge_base):
            print(
                f"::notice::mutation gate: {rel}'s diff vs {merge_base[:12]} is "
                "comment-only (no mutable code changed) — skipping",
                file=sys.stderr,
            )
            continue
        rel_py = rel.removeprefix("app/")
        rel_py = rel_py.removesuffix(".py")
        testfiles = with_unit_mirror(rel_py, _test_files_for(rel_py))
        if testfiles:
            matrix.append(_entry(rel, testfiles, merge_base))
            continue
        unit_mirror = f"tests/unit/{Path(rel_py).parent}/test_{Path(rel_py).stem}.py"
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


def _entry(module_rel: str, testfiles: list[str], merge_base: str) -> dict[str, object]:
    """Module matrix entry with the PR's changed line ranges for this file.

    The gate is diff-driven: a survivor only fails the lane when its mutation
    lands on a line the PR changed. Mutants on untouched lines are noted, not
    failures — otherwise a 1-line import fix would demand full-module test
    coverage.
    """
    ranges = _changed_line_ranges(f"apps/api/{module_rel}", merge_base)
    return {"module": module_rel, "testfiles": testfiles, "changed_lines": ranges}


def _changed_line_ranges(path: str, merge_base: str) -> list[list[int]]:
    """PR-changed line ranges for a file, from the merge-base diff (unified=0).

    Returns [] when ``merge_base`` is empty (local runs — see ``_merge_base``).
    In CI the diff MUST succeed — empty ranges would silently pass every
    survivor, so a git failure there is a hard lane error.
    """
    if not merge_base:
        return []
    try:
        out = subprocess.check_output(
            ["git", "diff", "--unified=0", merge_base, "HEAD", "--", path],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"::error::mutation gate: could not diff {path} against {merge_base}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
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
