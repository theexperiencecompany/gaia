#!/usr/bin/env python3
"""Coverage-based test impact selection.

A PR currently pays for all ~12k pytest tests in apps/api (~110-150s of pytest
at 16 workers on the home runner) to learn about a diff that usually touches
three files. This script turns a coverage database recorded WITH dynamic
contexts (``--cov-context=test``) into a source-file -> test-ids map, and then
turns a diff into the subset of tests that can actually see the change.

Two commands:

  record --coverage-db .coverage.unit --out test-impact-map-unit.json
      Read a coverage DB and emit the map.

  select --map test-impact-map-unit.json --changed changed-files.txt \
         --out selected.txt
      Emit the node ids to run (or the single line ``ALL``).

Safety is one-directional: every case we are not sure about widens to ALL.
The full suite on master is the backstop, so a wrong-but-wide answer costs
seconds and a wrong-but-narrow answer would cost a green PR on a broken tree.

Map schema (JSON):
  {"meta": {"sha": ..., "slice": ..., "version": 1},
   "files": {"app/foo.py": ["tests/unit/test_foo.py::test_a", ...]},
   "test_files": {"tests/unit/test_foo.py": ["tests/unit/test_foo.py::test_a"]}}
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

MAP_VERSION = 1

# Selecting more than this fraction of the suite is not worth the argv risk
# (10k node ids is ~1 MB, near ARG_MAX) nor the bookkeeping: just run it all.
ALL_THRESHOLD = 0.30

# A change to any of these invalidates the map wholesale: fixtures are wired in
# by name, so coverage cannot see which tests depend on which conftest.
GLOBAL_TEST_DEPS = ("conftest.py", "tests/helpers.py", "tests/factories.py")

ALL_MARKER = "ALL"

# Files under apps/api that no test can observe: tooling and prose. Anything
# else that is not app/ or tests/ (pyproject.toml, uv.lock, pytest.ini, the
# Dockerfile, scripts/) still widens to ALL. Measured 2026-08-28: a master
# merge that touched only .pre-commit-config.yaml made all four lanes run
# their full slice (2003 + 7160 + ... tests) for nothing.
INERT_SUFFIXES = (".md", ".mdx", ".rst", ".txt")
INERT_NAMES = frozenset(
    {
        ".pre-commit-config.yaml",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
        "CLAUDE.md",
        "AGENTS.md",
    }
)
INERT_DIRS = ("docs/",)

# Files anywhere in the repo that decide how pytest runs or what it runs in.
# The workspace lockfile is the ROOT uv.lock (there is no apps/api/uv.lock), the
# interpreter comes from .python-version, and the slice runner / this selector /
# the workflow decide what is collected at all — none of that is visible to
# coverage, so any of it changing invalidates the map wholesale.
SUITE_CONFIG_NAMES = frozenset(
    {"uv.lock", "pyproject.toml", ".python-version", "pytest.ini", "setup.cfg", "tox.ini"}
)
SUITE_CONFIG_PATHS = frozenset({"scripts/ci/run-python-slice.sh", ".github/workflows/main.yml"})
SUITE_CONFIG_PREFIXES = ("scripts/ci/test-impact", ".github/actions/setup-python-test-env/")

TEST_MODULE_PREFIX = "test_"
TEST_MODULE_SUFFIX = "_test.py"


def is_inert(rel: str) -> bool:
    """True for a path under apps/api that cannot change any test's outcome."""
    name = rel.rsplit("/", 1)[-1]
    return name in INERT_NAMES or rel.endswith(INERT_SUFFIXES) or rel.startswith(INERT_DIRS)


def is_suite_config(path: str) -> bool:
    """True for a repo-relative path that configures the test run itself."""
    name = path.rsplit("/", 1)[-1]
    return (
        name in SUITE_CONFIG_NAMES
        or path in SUITE_CONFIG_PATHS
        or path.startswith(SUITE_CONFIG_PREFIXES)
    )


def is_test_module(rel: str) -> bool:
    """True for a file pytest collects tests from (``test_*.py`` / ``*_test.py``)."""
    name = rel.rsplit("/", 1)[-1]
    return (name.startswith(TEST_MODULE_PREFIX) and name.endswith(".py")) or name.endswith(
        TEST_MODULE_SUFFIX
    )


# ── map recording ────────────────────────────────────────────────────────────


def normalise_context(context: str) -> str:
    """``tests/unit/test_foo.py::test_a|run`` -> ``tests/unit/test_foo.py::test_a``.

    coverage.py suffixes the dynamic context with the pytest phase (setup / run
    / teardown). The phase is noise here; a test that touches a file during
    setup is just as impacted as one that touches it in the body.
    """
    return context.split("|", 1)[0]


def normalise_path(path: str) -> str:
    """Normalise a measured filename to a repo-relative POSIX path.

    ``relative_files = true`` in pyproject means coverage already stores
    ``app/foo.py``, but combined data from another checkout can carry an
    absolute path or a ``./`` prefix.
    """
    text = path.replace("\\", "/")
    text = text.removeprefix("./")
    marker = "/apps/api/"
    if marker in text:
        text = text.split(marker, 1)[1]
    return text


def build_map(db_paths: list[str], sha: str, slice_name: str) -> dict[str, Any]:
    from coverage import CoverageData  # imported late: only `record` needs it

    files: dict[str, set[str]] = {}
    test_files: dict[str, set[str]] = {}

    for db_path in db_paths:
        data = CoverageData(basename=db_path)
        data.read()
        for measured in data.measured_files():
            src = normalise_path(measured)
            contexts_by_line = data.contexts_by_lineno(measured)
            for contexts in contexts_by_line.values():
                for raw in contexts:
                    node_id = normalise_context(raw)
                    # The empty context is coverage recorded outside any test
                    # (import time, session fixtures) — it names no test.
                    if not node_id or "::" not in node_id:
                        continue
                    files.setdefault(src, set()).add(node_id)
                    test_file = normalise_path(node_id.split("::", 1)[0])
                    test_files.setdefault(test_file, set()).add(node_id)

    return {
        "meta": {"sha": sha, "slice": slice_name, "version": MAP_VERSION},
        "files": {k: sorted(v) for k, v in sorted(files.items())},
        "test_files": {k: sorted(v) for k, v in sorted(test_files.items())},
    }


def cmd_record(args: argparse.Namespace) -> int:
    payload = build_map(args.coverage_db, args.sha, args.slice)
    Path(args.out).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    n_tests = len({t for tests in payload["files"].values() for t in tests})
    print(
        f"recorded {len(payload['files'])} source files, "
        f"{len(payload['test_files'])} test files, {n_tests} tests -> {args.out}"
    )
    if n_tests == 0:
        # Almost always means the run was missing --cov-context=test, or ran
        # under COVERAGE_CORE=sysmon (sys.monitoring cannot do dynamic
        # contexts). An empty map is worse than none: it selects nothing.
        print(
            "::warning::test-impact: map has no test contexts — was the run "
            "missing --cov-context=test, or was COVERAGE_CORE=sysmon set?",
            file=sys.stderr,
        )
    return 0


# ── selection ────────────────────────────────────────────────────────────────


def load_maps(paths: list[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    files: dict[str, set[str]] = {}
    test_files: dict[str, set[str]] = {}
    for path in paths:
        payload = json.loads(Path(path).read_text())
        for src, tests in payload.get("files", {}).items():
            files.setdefault(src, set()).update(tests)
        for test_file, tests in payload.get("test_files", {}).items():
            test_files.setdefault(test_file, set()).update(tests)
    return (
        {k: sorted(v) for k, v in files.items()},
        {k: sorted(v) for k, v in test_files.items()},
    )


def strip_prefix(path: str, prefix: str = "apps/api/") -> str | None:
    """Repo-relative -> apps/api-relative, or None if the path is outside it.

    Diffs arrive repo-relative (``apps/api/app/foo.py``) but a caller running
    inside apps/api may hand us the already-stripped form; accept both.
    """
    text = path.replace("\\", "/").strip()
    if not text:
        return None
    if text.startswith(prefix):
        return text[len(prefix) :]
    if text.startswith(("app/", "tests/")):
        return text
    return None


class Selection:
    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.reasons: list[str] = []
        self.select_all = False
        self.all_reason = ""

    def widen(self, reason: str) -> None:
        if not self.select_all:
            self.select_all = True
            self.all_reason = reason


def _classify_outside_api(path: str, sel: Selection) -> None:
    """A change outside apps/api: suite config or importable Python widens.

    Any Python outside (libs/shared/py, tools) can be imported by the API;
    coverage only mapped app/**, so the map cannot name its tests.
    """
    if is_suite_config(path):
        sel.widen(f"test-suite config changed: {path}")
    elif path.endswith(".py"):
        sel.widen(f"changed python outside apps/api: {path}")


def _classify_test_path(rel: str, sel: Selection, repo_root: Path) -> None:
    """A change under tests/: run the test module, widen on anything else."""
    if rel.rsplit("/", 1)[-1] in INERT_NAMES:
        return
    if not is_test_module(rel):
        # Snapshots, fixtures, cassettes, helper modules: pytest collects
        # nothing from the path itself, and the map only knows app/**, so
        # the tests that read them cannot be found — widen.
        sel.widen(f"non-test file under tests/ changed: {rel}")
        return
    # Run the whole file: a path is a valid pytest positional arg, and it
    # covers tests added in this diff that no map can know about.
    if (repo_root / rel).exists():
        sel.ids.add(rel)
        sel.reasons.append(f"changed test file {rel}")


def _classify_app_path(
    rel: str, sel: Selection, files: dict[str, list[str]], repo_root: Path
) -> None:
    """A change under app/: the mapped tests, or widen when the map has none."""
    if rel in files:
        sel.ids.update(files[rel])
        sel.reasons.append(f"{rel} covered by {len(files[rel])} tests")
    elif (repo_root / rel).exists():
        sel.widen(f"changed app file not in map (new or uncovered): {rel}")
    # A deleted app file that was never covered impacts nothing.


def _classify_change(
    raw: str, sel: Selection, files: dict[str, list[str]], repo_root: Path
) -> None:
    """Fold one changed path into ``sel`` (widen, add ids, or ignore)."""
    path = raw.replace("\\", "/").strip()
    rel = strip_prefix(path)
    if rel is None:
        _classify_outside_api(path, sel)
    elif any(rel.endswith(dep) or rel == dep for dep in GLOBAL_TEST_DEPS):
        sel.widen(f"shared test fixture changed: {rel}")
    elif rel.startswith("tests/"):
        _classify_test_path(rel, sel, repo_root)
    elif rel.startswith("app/"):
        _classify_app_path(rel, sel, files, repo_root)
    elif not is_inert(rel):
        # apps/api/pyproject.toml, uv.lock, Dockerfile, a script — anything
        # here can move the whole suite.
        sel.widen(f"non-source change under apps/api: {rel}")


def select_tests(
    changed: list[str],
    files: dict[str, list[str]],
    test_files: dict[str, list[str]],
    *,
    repo_root: Path,
    restrict_to: list[str],
    always: list[str],
) -> tuple[list[str], str, int, int]:
    """Return (node ids or [ALL_MARKER], reason, n_selected, n_total)."""
    sel = Selection()

    def in_scope(path: str) -> bool:
        return not restrict_to or any(
            path == root or path.startswith(root.rstrip("/") + "/") for root in restrict_to
        )

    total = len({t for f, tests in test_files.items() if in_scope(f) for t in tests})

    for raw in changed:
        _classify_change(raw, sel, files, repo_root)

    if sel.select_all:
        return [ALL_MARKER], sel.all_reason, total, total

    scoped = {i for i in sel.ids if in_scope(i.split("::", 1)[0])}

    always_paths = [a for a in always if (repo_root / a).exists()]
    # Drop ids already inside an always-on path so pytest is not handed both a
    # directory and node ids under it.
    scoped = {
        i
        for i in scoped
        if not any(i.startswith(a.rstrip("/") + "/") or i == a for a in always_paths)
    }

    estimated = sum(len(test_files.get(i, [i])) if "::" not in i else 1 for i in scoped)
    if total and estimated > total * ALL_THRESHOLD:
        reason = f"selection {estimated} exceeds {int(ALL_THRESHOLD * 100)}% of {total}"
        return [ALL_MARKER], reason, total, total

    node_ids = sorted(scoped) + [a for a in always_paths if in_scope(a)]
    if not node_ids:
        return [], "no impacted tests", 0, total
    head = sel.reasons[0] if sel.reasons else "always-on paths only"
    extra = f" +{len(sel.reasons) - 1} more" if len(sel.reasons) > 1 else ""
    return node_ids, head + extra, estimated, total


def cmd_select(args: argparse.Namespace) -> int:
    files, test_files = load_maps(args.map)
    changed = [line for line in Path(args.changed).read_text().splitlines() if line.strip()]
    if not files:
        node_ids, reason, n, total = [ALL_MARKER], "no map available", 0, 0
    else:
        node_ids, reason, n, total = select_tests(
            changed,
            files,
            test_files,
            repo_root=Path(args.repo_root),
            restrict_to=args.restrict_to,
            always=args.always,
        )

    Path(args.out).write_text("".join(f"{i}\n" for i in node_ids))
    if node_ids == [ALL_MARKER]:
        summary = f"selected ALL of {total or 'unknown'} tests ({reason})"
    else:
        summary = f"selected {n} of {total} tests ({reason})"
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(f"test impact: {summary}\n\n")
    return 0


# ── cli ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="coverage DB -> impact map")
    rec.add_argument("--coverage-db", action="append", required=True)
    rec.add_argument("--out", required=True)
    rec.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    rec.add_argument("--slice", default="")
    rec.set_defaults(func=cmd_record)

    sel = sub.add_parser("select", help="impact map + diff -> node ids")
    sel.add_argument("--map", action="append", required=True)
    sel.add_argument("--changed", required=True)
    sel.add_argument("--out", required=True)
    sel.add_argument("--repo-root", default=".", help="apps/api, for existence checks")
    sel.add_argument("--tests-root", default="tests", help="kept for CLI symmetry; unused")
    sel.add_argument(
        "--restrict-to",
        action="append",
        default=[],
        help="only emit ids under these paths (one slice's share of the suite)",
    )
    sel.add_argument(
        "--always",
        action="append",
        default=[],
        help="paths that always run, e.g. tests/contracts",
    )
    sel.set_defaults(func=cmd_select)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
