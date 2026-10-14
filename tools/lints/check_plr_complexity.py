#!/usr/bin/env python3
"""Touch-to-fix ratchet for ruff's PLR0911/0912/0913/0915 complexity rules.

``PLR0911``/``PLR0912``/``PLR0913``/``PLR0915`` (too many returns / branches /
arguments / statements) are re-enabled repo-wide, but the pre-existing debt at
the time they were switched on (``tools/lints/plr_complexity_baseline.txt``)
was too large to fix in one pass. A plain ``[tool.ruff.lint.per-file-ignores]``
entry would grandfather each listed file forever, silently, with no way to
notice a PR making an already-flagged function *worse* -- ruff's per-file
ignore silences a rule for the whole file, not just the violations recorded
at the time.

The ratchet mechanics (grandfathered only while untouched, expiring
deferrals, ``--update``) live in ``_ratchet.py`` and are shared with the other
baseline-carrying lints; this script only knows how to ask ruff for the
current violations.

One narrow waiver: a LangChain ``@tool`` function is exempt from ``PLR0913``
only, because its parameters are the schema the model sees (see ``_is_exempt``).

Usage::

    python3 tools/lints/check_plr_complexity.py       # check (exits 1 on failure)
    python3 tools/lints/check_plr_complexity.py --update   # record the current baseline
"""

from __future__ import annotations

import ast
from functools import cache
import json
from pathlib import Path
import subprocess
import sys

from _ratchet import REPO_ROOT, RatchetRule, run_ratchet

RULE = "plr-complexity-ratchet"
WHY = (
    "PLR0911/0912/0913/0915 complexity debt is grandfathered per file, but only "
    "until a PR touches that file -- then its known violations must be fixed, "
    "same as any new one"
)
DOC = "tools/lints/README.md#plr-complexity-ratchet"

_HERE = Path(__file__).resolve().parent
BASELINE = _HERE / "plr_complexity_baseline.txt"
PLR_RULES = ("PLR0911", "PLR0912", "PLR0913", "PLR0915")

# The only rule this ratchet waives, and the decorator it waives it for -- see
# `_is_exempt` for why a @tool's argument list is a contract, not complexity.
# The decorator is matched by its import binding, not its spelling, so an
# unrelated `@tool` / `@mcp.tool` gets no waiver and an aliased import does.
_ARG_COUNT_RULE = "PLR0913"
_TOOL_DECORATOR = "langchain_core.tools.tool"

# Pinned to the same ruff version as the "Python ruff" CI lane
# (.github/workflows/code-quality.yml) -- bump both together. `uvx` resolves
# it without requiring a separate "install ruff onto PATH" CI step.
_RUFF_CMD = ["uvx", "--no-build", "ruff@0.14.13"]

_BASELINE_HEADER = """\
# PLR0911/0912/0913/0915 complexity grandfather baseline.
# See tools/lints/check_plr_complexity.py -- this is a TOUCH-TO-FIX ratchet,
# not a static exemption: a file listed here only stays quiet while untouched.
# The moment a PR modifies a listed file, its violations here must be fixed in
# that same PR, and this line deleted. New violations (new file, or a rule a
# file didn't already have) are never grandfathered by this list.
#
# One line per (file, rule), tab-separated, sorted. Regenerate with:
#   python3 tools/lints/check_plr_complexity.py --update
#
# A line may carry a third field, "deferred-until=YYYY-MM-DD; <reason>", to
# keep a touched file's known violation from failing until that date (CI
# warns instead). Past the date it fails again: fix it, or renew the deferral
# with a fresh reason. --update keeps the field.
"""


def _import_bindings(tree: ast.Module) -> dict[str, str]:
    """Map each name a module's imports bind to the dotted path it refers to.

    ``from a.b import c as d`` binds ``d`` to ``a.b.c``; ``import a.b as e``
    binds ``e`` to ``a.b``; a bare ``import a.b`` binds only ``a``.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    head = alias.name.split(".", 1)[0]
                    bindings[head] = head
    return bindings


def _decorator_target(node: ast.expr, bindings: dict[str, str]) -> str | None:
    """Resolve a decorator to the dotted path it imports from, or None if unbound.

    Handles ``@name``, ``@name(...)`` and ``@mod.attr`` chains; the leading name
    must come from an import, so a local or unimported ``tool`` resolves to None.
    """
    if isinstance(node, ast.Call):
        node = node.func
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in bindings:
        return None
    return ".".join([bindings[node.id], *reversed(attrs)])


@cache
def _tool_decorated_def_lines(path: Path) -> frozenset[int]:
    """Return the ``def`` line of every LangChain ``@tool``-decorated function in a file.

    Ruff reports PLR0913 at the ``def`` line (decorators are separate nodes),
    which is also ``FunctionDef.lineno`` -- so the two line up directly.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bindings = _import_bindings(tree)
    return frozenset(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(_decorator_target(d, bindings) == _TOOL_DECORATOR for d in node.decorator_list)
    )


def _is_exempt(code: str, filename: str, row: int) -> bool:
    """Report the one waiver this ratchet grants: argument count on a @tool.

    A LangChain ``@tool`` function's parameters ARE the schema the model sees,
    so the argument list is the tool's contract rather than accidental
    complexity -- collapsing it into nested objects would change what the LLM
    is asked to emit. Only the argument-count rule is waived; too many returns,
    branches, or statements inside the body are ordinary complexity and still
    fail.
    """
    if code != _ARG_COUNT_RULE:
        return False
    return row in _tool_decorated_def_lines(Path(filename).resolve())


def _current_violations() -> dict[tuple[str, str], int]:
    """Every (file, rule) violation in the repo right now, mapped to its line.

    Full-repo scan, keyed by (file, rule) to match the baseline's granularity
    -- if a file has several violations of the same rule, this keeps the
    first line encountered, which is enough to make a failure clickable.
    """
    proc = subprocess.run(  # nosec B603 - pinned ruff argv, no shell
        [
            *_RUFF_CMD,
            "check",
            "--select",
            ",".join(PLR_RULES),
            "--output-format",
            "json",
            ".",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"{RULE}: ruff failed unexpectedly (exit {proc.returncode})")
    violations = json.loads(proc.stdout)
    out: dict[tuple[str, str], int] = {}
    for v in violations:
        row = v["location"]["row"]
        if _is_exempt(v["code"], v["filename"], row):
            continue
        path = Path(v["filename"]).resolve().relative_to(REPO_ROOT).as_posix()
        out.setdefault((path, v["code"]), row)
    return out


_RATCHET = RatchetRule(
    name=RULE,
    why=WHY,
    doc=DOC,
    baseline=BASELINE,
    header=_BASELINE_HEADER,
    script="tools/lints/check_plr_complexity.py",
    fix_new="new complexity violation -- simplify the function",
)


def main(argv: list[str]) -> int:
    return run_ratchet(_RATCHET, _current_violations(), argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
