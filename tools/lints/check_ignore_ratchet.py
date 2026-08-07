#!/usr/bin/env python3
"""One-way ratchet on ruff's two escape-hatch lists in the root ``pyproject.toml``.

``[tool.ruff.lint] ignore`` and ``[tool.ruff.lint.per-file-ignores]`` are the two
places a rule can be switched off. Both are the residue of a cleanup campaign, so
both may only ever *shrink*: a rule silently added back to either list re-opens
exactly the hole the campaign closed, and a config edit is invisible in review in
a way a failing check is not.

This compares the current lists against a checked-in baseline as **sets**, not
counts (a count check passes when one entry is removed and another added), and
fails naming every entry that was added. Removals always pass — that is the
ratchet turning.

Deliberately loosening a list is still allowed, but it costs a visible commit:
run ``--update`` and the baseline diff shows the new escape hatch on its own
line, for a reviewer to accept or reject.

Usage::

    python3 tools/lints/check_ignore_ratchet.py       # check (exits 1 on growth)
    python3 tools/lints/check_ignore_ratchet.py --update   # record the current lists

Stdlib only, like the AST rules beside it; wired into the api pre-commit config.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib
from typing import NamedTuple

from _common import Violation, report_rule

RULE = "ignore-ratchet"
WHY = (
    "ruff's ignore lists and mypy's loosening overrides are cleanup residue — "
    "they may only shrink, never grow"
)
DOC = "tools/lints/README.md#ignore-ratchet"

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
BASELINE = _HERE / "ignore_ratchet_baseline.txt"

GLOBAL_SCOPE = "ignore"
PER_FILE_SCOPE = "per-file-ignores"
MYPY_SCOPE = "mypy-override"

#: Per-module mypy settings that *weaken* checking when set to this value. A
#: strict-island override that sets the same keys to True is a tightening and is
#: deliberately not tracked — this ratchet guards holes, not strictness.
_MYPY_LOOSENINGS: dict[str, bool] = {
    "disallow_untyped_defs": False,
    "disallow_incomplete_defs": False,
    "disallow_untyped_calls": False,
    "disallow_untyped_decorators": False,
    "disallow_any_generics": False,
    "disallow_subclassing_any": False,
    "check_untyped_defs": False,
    "strict_optional": False,
    "strict_equality": False,
    "warn_return_any": False,
    "warn_unused_ignores": False,
    "warn_unreachable": False,
    "no_implicit_reexport": False,
    "extra_checks": False,
    "ignore_errors": True,
    "ignore_missing_imports": True,
}

_BASELINE_HEADER = """\
# Ruff escape-hatch ratchet baseline — see tools/lints/check_ignore_ratchet.py.
#
# One line per escape hatch, sorted. Three shapes:
#   ignore<TAB><rule>                        -> [tool.ruff.lint] ignore
#   per-file-ignores<TAB><glob><TAB><rule>   -> [tool.ruff.lint.per-file-ignores]
#   mypy-override<TAB><module><TAB><setting> -> a [[tool.mypy.overrides]] block
#                                               that weakens checking
#
# This list may only shrink. Deleting lines is the ratchet turning and always
# passes. Adding one is a deliberate loosening: it must arrive in its own commit
# (regenerate with `--update`) so a reviewer sees the hole being re-opened.
"""


class Entry(NamedTuple):
    """One switched-off rule: global, or scoped to one file glob."""

    scope: str
    key: str  # the file glob; "" for the global ignore list
    rule: str

    def render(self) -> str:
        parts = (
            (self.scope, self.rule)
            if self.scope == GLOBAL_SCOPE
            else (self.scope, self.key, self.rule)
        )
        return "\t".join(parts)

    def describe(self) -> str:
        if self.scope == GLOBAL_SCOPE:
            return f"`{self.rule}` added to the global [tool.ruff.lint] ignore list"
        if self.scope == MYPY_SCOPE:
            return f"mypy checking weakened for `{self.key}` via `{self.rule}`"
        return f"`{self.rule}` added to per-file-ignores for `{self.key}`"


def _parse_entry(line: str, lineno: int) -> Entry:
    fields = line.split("\t")
    if len(fields) == 2 and fields[0] == GLOBAL_SCOPE:
        return Entry(GLOBAL_SCOPE, "", fields[1])
    if len(fields) == 3 and fields[0] in (PER_FILE_SCOPE, MYPY_SCOPE):
        return Entry(fields[0], fields[1], fields[2])
    raise ValueError(f"{BASELINE.name}:{lineno}: malformed entry {line!r}")


def read_baseline() -> set[Entry]:
    """Parse the checked-in baseline; a missing file is an empty set."""
    if not BASELINE.exists():
        return set()
    entries: set[Entry] = set()
    for lineno, raw in enumerate(BASELINE.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.add(_parse_entry(line, lineno))
    return entries


def read_current() -> set[Entry]:
    """Flatten every escape hatch out of the root pyproject.toml."""
    tool = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]
    lint = tool["ruff"]["lint"]
    entries = {Entry(GLOBAL_SCOPE, "", rule) for rule in lint.get(GLOBAL_SCOPE, ())}
    for glob, rules in lint.get(PER_FILE_SCOPE, {}).items():
        entries.update(Entry(PER_FILE_SCOPE, glob, rule) for rule in rules)
    entries.update(_mypy_loosenings(tool.get("mypy", {})))
    return entries


def _mypy_loosenings(mypy_cfg: dict[str, object]) -> set[Entry]:
    """Per-module mypy settings that switch a check off, one entry per module.

    Widening an existing block's ``module`` list is the dangerous edit this
    catches: adding ``"app.services.*"`` beside ``"tests.*"`` silently drops
    type checking for every service, and reads as a one-word diff.
    """
    entries: set[Entry] = set()
    overrides = mypy_cfg.get("overrides", [])
    if not isinstance(overrides, list):
        return entries
    for block in overrides:
        if not isinstance(block, dict):
            continue
        modules = block.get("module", [])
        if isinstance(modules, str):
            modules = [modules]
        for setting, loosened_value in _MYPY_LOOSENINGS.items():
            if setting in block and block[setting] == loosened_value:
                entries.update(Entry(MYPY_SCOPE, str(m), setting) for m in modules)
    return entries


def write_baseline(entries: set[Entry]) -> None:
    body = "\n".join(entry.render() for entry in sorted(entries))
    BASELINE.write_text(f"{_BASELINE_HEADER}{body}\n", encoding="utf-8")


def _global_ignore_span(lines: list[str]) -> tuple[int, int]:
    """Index range of the ``ignore = [ ... ]`` array inside ``[tool.ruff.lint]``."""
    in_section = False
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("["):
            in_section = stripped == "[tool.ruff.lint]"
        elif in_section and stripped.startswith("ignore") and stripped.endswith("["):
            for j in range(i, len(lines)):
                if lines[j].strip() == "]":
                    return i, j
            return i, len(lines) - 1
    return 0, -1


def locate(entry: Entry, lines: list[str]) -> int:
    """1-based pyproject.toml line for an entry, so the failure is clickable."""
    if entry.scope == MYPY_SCOPE:
        needle = f'"{entry.key}"'
        for i, raw in enumerate(lines):
            if raw.strip().startswith(needle):
                return i + 1
        return 1
    if entry.scope == PER_FILE_SCOPE:
        needle = f'"{entry.key}"'
        for i, raw in enumerate(lines):
            if raw.lstrip().startswith(needle):
                return i + 1
        return 1
    start, end = _global_ignore_span(lines)
    for i in range(start, end + 1):
        if f'"{entry.rule}"' in lines[i]:
            return i + 1
    return start + 1


def main(argv: list[str]) -> int:
    current = read_current()

    if "--update" in argv:
        previous = read_baseline()
        write_baseline(current)
        print(
            f"{RULE}: baseline updated — {len(current)} escape hatch(es) "
            f"(+{len(current - previous)} / -{len(previous - current)}). "
            "Commit the diff so the change is reviewable."
        )
        return 0

    baseline = read_baseline()
    added = sorted(current - baseline)
    removed = sorted(baseline - current)

    if added:
        lines = PYPROJECT.read_text(encoding="utf-8").splitlines()
        report_rule(
            RULE,
            WHY,
            DOC,
            [
                Violation(
                    path=PYPROJECT,
                    line=locate(entry, lines),
                    detail=f"new escape hatch: {entry.describe()}",
                    fix=(
                        f"delete `{entry.rule}` from that entry and fix the code it silences. "
                        "If the exemption is genuinely warranted, justify it in review and "
                        "record it with `python3 tools/lints/check_ignore_ratchet.py --update` "
                        "so the baseline diff shows it."
                    ),
                )
                for entry in added
            ],
        )
        print(
            f"\n{len(added)} escape hatch(es) added. These lists may only shrink — "
            "see tools/lints/README.md#ignore-ratchet.",
            file=sys.stderr,
        )
        return 1

    if removed:
        print(f"{RULE}: {len(removed)} escape hatch(es) removed since the baseline — nice.")
        for entry in removed:
            print(f"  - {entry.describe().replace('added to', 'gone from')}")
        print("  Lock the win in with: python3 tools/lints/check_ignore_ratchet.py --update")

    print(f"{RULE}: {len(current)} escape hatch(es), none added since the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
