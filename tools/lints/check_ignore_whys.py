#!/usr/bin/env python3
"""Why-comments are mandatory on every lint escape hatch in ``pyproject.toml``.

Replaces the old set-ratchet (``check_ignore_ratchet.py``): a baseline that
blocks additions cannot tell a load-bearing exemption from stale debt, and the
stock never gets re-litigated. The durable governance is documentation AT the
escape hatch, enforced mechanically:

  - every rule in ``[tool.ruff.lint] ignore``
  - every glob in ``[tool.ruff.lint.per-file-ignores]``
  - every ``[[tool.mypy.overrides]]`` block

must carry a WHY — a trailing comment on the entry's line, or a comment block
directly above it. One comment may cover a run of consecutive entries that
share a rationale (the normal shape here); a blank line or an undocumented
entry ends its reach, so newly appended escapes fail until annotated.

What this does NOT do: judge the reason (review does), or block additions by
set-comparison (nothing to compare against — there is no baseline). An escape
hatch with a stated why is a decision; one without is a hole.

Usage::

    python3 tools/lints/check_ignore_whys.py

Stdlib only; parsed textually so any Python >= 3.9 runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys

from _common import Violation, report_rule

RULE = "ignore-whys"
WHY = (
    "a lint escape hatch without a written why is a hole nobody can audit — "
    "state the rationale beside every ignore / per-file-ignores / mypy override"
)
DOC = "tools/lints/README.md#ignore-whys"

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

_MIN_WHY_LEN = 8


@dataclass(frozen=True)
class Entry:
    """One escape hatch that must be justified."""

    label: str  # human-readable subject, e.g. per-file-ignores["apps/..."]
    line: int  # 1-based pyproject.toml line, for the clickable failure


def _comment_prose(line: str) -> str | None:
    """The prose after a ``#``, or None when the line carries no comment."""
    i = line.find("#")
    if i == -1:
        return None
    return line[i + 1 :].strip()


def _documented(lines: list[str], idx0: int) -> bool:
    """True if the entry line at index ``idx0`` has a trailing comment with
    prose, or the immediately-preceding non-blank line is a comment with
    prose.

    Deliberately STRICT adjacency: a rationale must sit beside its entry, not
    anywhere above it — otherwise a freshly appended escape hatch silently
    inherits whatever comment happens to sit higher in the array."""
    own = _comment_prose(lines[idx0])
    if own and len(own) >= _MIN_WHY_LEN:
        return True
    j = idx0 - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0:
        return False
    if not lines[j].strip().startswith("#"):
        return False
    # Walk up the contiguous comment block; any line in it may carry the prose.
    while j >= 0 and lines[j].strip().startswith("#"):
        prose = _comment_prose(lines[j])
        if prose and len(prose) >= _MIN_WHY_LEN:
            return True
        j -= 1
    return False


_KEY_VAL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*(#.*)?$")
_MODULE_ARRAY_END_RE = re.compile(r"^\s*]\s*$")


def _section_span(lines: list[str], header: str) -> tuple[int, int]:
    """Half-open [start, end) line-index span of a TOML table (or the end of
    file). start points at the first line AFTER the header."""
    start = next(i for i, ln in enumerate(lines) if ln.strip() == header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("["):
            end = i
            break
    return start + 1, end


# Entry shapes whose lines never break a comment's reach above them: quoted
# keys in both ruff sections ("RULE", / "glob" = [ … ]).
def ruff_entries(lines: list[str]) -> list[Entry]:
    """Every ``ignore`` rule and every ``per-file-ignores`` glob, with its line."""
    out: list[Entry] = []

    # Global ignore array inside [tool.ruff.lint].
    s, e = _section_span(lines, "[tool.ruff.lint]")
    in_ignore = False
    for i in range(s, e):
        st = lines[i].strip()
        if st.startswith("ignore") and st.endswith("["):
            in_ignore = True
        elif in_ignore:
            if st == "]":
                in_ignore = False
            elif st.startswith('"'):
                out.append(Entry(f'ignore["{st.split(chr(34))[1]}"]', i + 1))

    # Per-file-ignores keys form their own table.
    s, e = _section_span(lines, "[tool.ruff.lint.per-file-ignores]")
    for i in range(s, e):
        st = lines[i].strip()
        m = re.match(r'^"([^"]+)"\s*=', st)
        if m:
            out.append(Entry(f'per-file-ignores["{m.group(1)}"]', i + 1))
    return out


def mypy_entries(lines: list[str]) -> list[Entry]:
    """Every ``[[tool.mypy.overrides]]`` block that weakens checking, at the
    line where the block starts. Parsed textually (any weakening key set to
    ``false``, or ``ignore_errors``/``ignore_missing_imports`` to ``true``)."""
    weaken_false = {
        "disallow_untyped_defs",
        "disallow_incomplete_defs",
        "disallow_untyped_calls",
        "disallow_untyped_decorators",
        "disallow_any_generics",
        "disallow_subclassing_any",
        "check_untyped_defs",
        "strict_optional",
        "strict_equality",
        "warn_return_any",
        "warn_unreachable",
        # defaults TRUE: an override setting it FALSE silences dead-ignore
        # detection, so stale `type: ignore` comments rot unnoticed
        "warn_unused_ignores",
        "no_implicit_reexport",
        "extra_checks",
    }
    weaken_true = {"ignore_errors", "ignore_missing_imports"}

    s, _e = _section_span(lines, "[tool.mypy]")
    out: list[Entry] = []
    i = s
    while i < len(lines):
        if lines[i].strip() != "[[tool.mypy.overrides]]":
            i += 1
            continue
        start = i
        weakened: set[str] = set()
        modules: list[str] = []
        in_modules = False
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith("[["):
            raw = lines[j]
            st = raw.strip()
            if st.startswith("module") and "=" in st:
                value = st.split("=", 1)[1].strip()
                # Only an array left open on this line continues onto the next;
                # a scalar or a single-line array is already complete.
                in_modules = value.startswith("[") and not value.endswith("]")
                modules += [m.strip('" ') for m in value.strip("[]").split(",") if m.strip()]
            elif in_modules:
                if _MODULE_ARRAY_END_RE.match(raw):
                    in_modules = False
                else:
                    modules.append(st.strip(', "'))
            else:
                kv = _KEY_VAL_RE.match(raw)
                if kv:
                    key, val = kv.group(1), kv.group(2)
                    if key in weaken_false and val == "false":
                        weakened.add(key)
                    if key in weaken_true and val == "true":
                        weakened.add(key)
                    # any non-empty disable_error_code list weakens checking
                    if key == "disable_error_code" and val not in ("[]", '""'):
                        weakened.add("disable_error_code")
            j += 1
        if weakened:
            label = ", ".join(modules[:3])
            more = "" if len(modules) <= 3 else f" (+{len(modules) - 3} more)"
            out.append(
                Entry(
                    f"mypy-override[{label}{more}] ({', '.join(sorted(weakened))})",
                    start + 1,
                )
            )
        i = j
    return out


def main(argv: list[str]) -> int:  # noqa: ARG001 -- CLI symmetry with the sibling checkers
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines()

    entries = [*ruff_entries(lines), *mypy_entries(lines)]
    violations = [
        Violation(
            path=PYPROJECT,
            line=entry.line,
            detail=f"{entry.label} has no why-comment",
            fix=(
                "add the rationale as a trailing comment or a comment block "
                "directly above — one sentence; if you cannot state it, fix the "
                "code instead of exempting it"
            ),
        )
        for entry in entries
        if not _documented(lines, entry.line - 1)
    ]

    if violations:
        report_rule(RULE, WHY, DOC, violations)
        print(f"\n{len(violations)} escape hatch(es) without a why.", file=sys.stderr)
        return 1

    print(f"{RULE}: OK — {len(entries)} escape hatch(es), all documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
