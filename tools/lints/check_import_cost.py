#!/usr/bin/env python3
"""Import-cost budgets for the layers that are supposed to be cheap.

A constants module that costs 1.6 s to import is not a constants module. The
cost is never local either: `import app.constants.llm` pulled transformers,
langchain_core and langsmith, so every test session, every worker boot and
every `python -c` that touched it paid for a model library it never used.

Two budgets, both discovered rather than listed, so a new file is covered the
moment it exists:

- every module under app/constants, app/config, app/utils and app/models is
  imported ALONE in a fresh subprocess, and its cost is its own body plus
  everything it is the first to import — which is exactly what `-X importtime`
  reports as the cumulative column for the root of a lone import.
- the three entry points every process starts from get a budget of their own.

No package names appear here, and there is no baseline. A heavy dependency is
caught the moment it reaches a hot path, which is the only place it costs
anything; where it may be imported FROM is the static half, and belongs in
[tool.importlinter]'s layers contract rather than in a list here.

Usage::

    python3 tools/lints/check_import_cost.py            # check (exits 1 on failure)
    python3 tools/lints/check_import_cost.py --report   # print every cost, gate nothing
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import subprocess
import sys

from _common import Violation, report_rule

RULE = "import-cost"
WHY = (
    "a module in a base layer is imported by everything above it, so its import "
    "cost is paid by every test session, every worker boot and every CLI start"
)
DOC = "tools/lints/README.md#import-cost"

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"

# The layers nothing above them can avoid importing. Discovered, not listed:
# every git-tracked .py under these is measured, so a new file is covered the
# moment it is added.
LAYER_ROOTS = ("app/constants", "app/config", "app/utils", "app/models")

# What a module in one of those layers may cost when imported on its own.
# Measured 2026-09-17 across all 224 of them: a real constants module (enums
# and strings) lands at 110-232 ms, of which ~30 ms is interpreter start, and
# 36 of the 44 under app/constants already fit inside 300 ms. That is the
# shape the budget is drawn around — room for a module that needs pydantic,
# and nowhere near enough for a model library.
MODULE_BUDGET_MS = 300

# The three modules every process in this repo starts from. Their budgets are
# set from a measurement rather than an aspiration — see ENTRY_BUDGET_MS.
ENTRY_POINTS = ("tests.conftest", "app.main", "app.worker")

# PROVISIONAL. Measured 2026-09-17, minimum of three serial runs, on a box
# whose 1-minute load average was 33-53 on 16 threads — the same module read
# 18.7 s and 73.5 s minutes apart. Set at ~1.5x the cheapest reading
# (conftest 4491, main 18656, worker 12085) so normal growth does not red a PR,
# but re-measure these on an idle box before anyone trusts them, and lower them
# in the same commit as any import-graph fix or the ratchet stops ratcheting.
ENTRY_BUDGET_MS = {
    "tests.conftest": 7000,
    "app.main": 28000,
    "app.worker": 18000,
}

# `-X importtime` competes with everything else on the box, and this lane runs
# beside the test and mutation lanes. One run decides the common case; only a
# module that BLEW its budget is measured again, because that is the only place
# a 20 ms jitter can change the answer. A module at 40 ms does not flake to 300.
CONFIRM_RUNS = 3

# Fresh subprocesses are independent, but the box is shared and this lane holds
# one governor slot. Four keeps a full sweep near two minutes without becoming
# the reason another lane queues.
IMPORT_WORKERS = 4

# `import time: <self us> | <cumulative us> | <2 spaces per level><module>`
IMPORTTIME_RE = re.compile(r"^import time:\s+(\d+) \|\s+(\d+) \|(\s*)(\S+)$")
INDENT_PER_LEVEL = 2


@dataclass
class Node:
    """One line of `-X importtime`, linked to the parent that triggered it."""

    name: str
    self_us: int
    cumulative_us: int
    children: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class Measurement:
    """What importing one module alone cost, and what it spent the time on."""

    module: str
    cost_ms: int
    chain: str
    error: str = ""


def tracked_modules() -> list[str]:
    """Every git-tracked module under the budgeted layers, as dotted names."""
    roots = [f"apps/api/{root}" for root in LAYER_ROOTS]
    listed = subprocess.run(  # nosec B603 B607 - fixed argv, no shell, git off PATH
        ["git", "ls-files", "-z", *roots],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    modules = []
    for path in listed.split("\0"):
        if not path.endswith(".py"):
            continue
        relative = path[len("apps/api/") :].removesuffix(".py").removesuffix("/__init__")
        modules.append(relative.replace("/", "."))
    return sorted(set(modules))


def interpreter() -> Path:
    """Return the Python that can import the app, or die saying it is missing."""
    for candidate in (
        API_ROOT / ".venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"{RULE}: no synced venv under {API_ROOT}/.venv or {REPO_ROOT}/.venv. "
        "This check imports the real modules; it cannot answer without the real "
        "dependencies. Run: cd apps/api && uv sync --frozen --group backend --group dev"
    )


def parse_importtime(text: str) -> Node | None:
    """Build the import tree from `-X importtime` output.

    It prints post-order — every child before the parent that triggered it —
    so the reversed stream is the tree in reading order, and the root is the
    module we asked for.
    """
    rows = []
    for line in text.splitlines():
        match = IMPORTTIME_RE.match(line)
        if match:
            self_us, cumulative_us, indent, name = match.groups()
            rows.append(
                (len(indent) // INDENT_PER_LEVEL, Node(name, int(self_us), int(cumulative_us)))
            )
    if not rows:
        return None
    rows.reverse()
    root_depth, root = rows[0]
    stack = {root_depth: root}
    for depth, node in rows[1:]:
        parent = stack.get(depth - 1)
        if parent is not None:
            parent.children.append(node)
        stack[depth] = node
    return root


def hot_chain(root: Node) -> str:
    """Return the most expensive path out of a module: what it imports, and why.

    One path, not a tree: the reader needs the edge to cut, and the costliest
    child at every step is the edge that is actually paying for the module.
    """
    names = [root.name]
    node = root
    while node.children:
        node = max(node.children, key=lambda child: child.cumulative_us)
        names.append(f"{node.name} ({node.cumulative_us // 1000} ms)")
    return " -> ".join(names)


def measure(module: str, python: Path) -> Measurement:
    """Import one module alone in a fresh subprocess and report what it cost."""
    env = dict(
        os.environ,
        ENV="development",
        PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "libs"), str(API_ROOT)]),
    )
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.run(  # nosec B603 - interpreter and module are ours
        [str(python), "-X", "importtime", "-c", f"import {module}"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        return Measurement(module, 0, "", error=tail or f"exited {proc.returncode}")
    root = parse_importtime(proc.stderr)
    if root is None or root.name != module:
        return Measurement(module, 0, "", error="-X importtime reported no root for this module")
    return Measurement(module, root.cumulative_us // 1000, hot_chain(root))


def measure_all(modules: list[str], python: Path) -> list[Measurement]:
    with ThreadPoolExecutor(max_workers=IMPORT_WORKERS) as pool:
        return list(pool.map(lambda module: measure(module, python), modules))


def confirm(over: list[Measurement], python: Path) -> list[Measurement]:
    """Re-measure what blew its budget and keep the cheapest run of each.

    The box runs the test and mutation lanes on the same cores, so a single
    slow read is a coin flip, not a regression. Only the modules that failed
    are re-run: re-running the whole sweep three times costs six minutes to
    change no answer.
    """
    best = {m.module: m for m in over}
    for _ in range(CONFIRM_RUNS - 1):
        for again in measure_all(sorted(best), python):
            if not again.error and again.cost_ms < best[again.module].cost_ms:
                best[again.module] = again
    return [best[module] for module in sorted(best)]


def budget_for(module: str) -> int:
    return ENTRY_BUDGET_MS.get(module, MODULE_BUDGET_MS)


def over_budget(measurements: list[Measurement]) -> list[Measurement]:
    return [m for m in measurements if m.error or m.cost_ms > budget_for(m.module)]


def module_path(module: str) -> Path:
    """Where a dotted module lives, for the annotation a reader clicks."""
    base = API_ROOT / Path(*module.split("."))
    return base.with_suffix(".py") if base.with_suffix(".py").is_file() else base / "__init__.py"


def violation(measurement: Measurement) -> Violation:
    budget = budget_for(measurement.module)
    if measurement.error:
        return Violation(
            path=module_path(measurement.module),
            line=1,
            detail=f"{measurement.module} could not be imported: {measurement.error}",
            fix="This check cannot measure what it cannot import — fix the import, or the venv.",
        )
    return Violation(
        path=module_path(measurement.module),
        line=1,
        detail=(
            f"{measurement.module} costs {measurement.cost_ms} ms to import alone "
            f"(budget {budget} ms); most of it goes to {measurement.chain}"
        ),
        fix=(
            "Cut the first edge in that chain. A base-layer module must not reach up "
            "into a layer above it, and a type-only import is still a runtime import "
            "here (this repo does not use TYPE_CHECKING) — move the shared type down "
            "instead of importing the heavy module to name it."
        ),
    )


def write_trend(measurements: list[Measurement]) -> None:
    """Record the entry points' cost as a trend. Never a gate — a number to watch."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    rows = ["| entry point | import cost | budget |", "| --- | --- | --- |"]
    rows += [
        f"| `{m.module}` | {m.cost_ms} ms | {budget_for(m.module)} ms |"
        for m in measurements
        if m.module in ENTRY_BUDGET_MS
    ]
    with Path(summary).open("a") as handle:
        handle.write("### Import cost\n\n" + "\n".join(rows) + "\n")


def main(argv: list[str]) -> int:
    python = interpreter()
    targets = tracked_modules() + list(ENTRY_POINTS)
    measurements = measure_all(targets, python)
    write_trend(measurements)

    if "--report" in argv:
        for m in sorted(measurements, key=lambda m: -m.cost_ms):
            print(f"  {m.cost_ms:6d} ms  {m.module}{'  ' + m.error if m.error else ''}")
        return 0

    failures = confirm(over_budget(measurements), python)
    failures = [m for m in failures if m.error or m.cost_ms > budget_for(m.module)]
    if failures:
        report_rule(RULE, WHY, DOC, [violation(m) for m in failures])
        return 1
    print(f"{RULE}: {len(measurements)} module(s) measured, all inside their import budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
