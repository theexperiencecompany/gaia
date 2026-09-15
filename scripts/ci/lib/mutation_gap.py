#!/usr/bin/env python3
"""Which of a module's PR-changed lines could a mutant have lived on?

The mutation lane reports SKIP when mutmut found no mutant with a covering
test. That single message covered two facts that need opposite responses:

* mutmut could not generate a mutant on the changed lines at all — imports,
  constants, docstrings, or the interior lines of a multi-line statement
  (mutmut scopes by a node's START line, so `url=X,` on line 199 of a call that
  opens on line 180 can never host one) — and silence is right; or
* mutmut generated mutants there and NO mapped test executes them — a real gap
  that used to pass the gate.

This prints the second kind, one line number per line. It asks mutmut the same
question the lane asks, through the same `create_mutations(covered_lines=…)`
scoping and with the same decorator patch loaded, rather than re-deriving
"mutable" from the AST: a second definition of the rule is how line 199 was
reported as unreachable by a test that executes it.

Usage: mutation_gap.py <module.py> '<[[start,end],...]>'
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

# scripts/test holds the lane's own mutmut patches; loaded the way mutation.sh
# loads them so this answers exactly what the lane would generate.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "test"))

import libcst as cst
from mutmut.mutation.file_mutation import create_mutations
import mutmut_decorated_patch  # noqa: F401  # side-effect import: patches mutmut's visitor to mutate decorated defs, as the lane does


def _mutants_on(path: str, source: str, lines: set[int]) -> int:
    try:
        _, mutations, _, _ = create_mutations(path, source, covered_lines=lines)
    except Exception:  # libcst raises its own parse errors; any of them means "nothing to mutate here", not a lane failure
        return 0
    # Only mutants inside a def count. mutmut records a kill through the
    # trampoline it installs on the enclosing function; a module-level mutant
    # (a constant) has no trampoline, so no test can ever be credited with
    # killing it — which is why every changed constants file read as "no
    # covering test" and was, correctly, a skip. Checked by TYPE, not truth:
    # mutmut tags a class-body field or enum member with its own statement as
    # the enclosing node, which is truthy and just as trampoline-less.
    return sum(
        1 for m in mutations if isinstance(m.contained_by_top_level_function, cst.FunctionDef)
    )


def mutable_changed_lines(path: str, source: str, ranges: list[list[int]]) -> list[int]:
    """Changed lines on which mutmut generates at least one mutant."""
    changed = sorted({n for start, end in ranges for n in range(start, end + 1)})
    # One pass over the whole scope first: the common benign case (imports,
    # constants, deletions) returns here without a per-line parse.
    if not changed or _mutants_on(path, source, set(changed)) == 0:
        return []
    return [line for line in changed if _mutants_on(path, source, {line})]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: mutation_gap.py <module.py> '<ranges-json>'", file=sys.stderr)
        return 2
    path, ranges_json = argv[1], argv[2]
    try:
        ranges = json.loads(ranges_json or "[]")
    except json.JSONDecodeError as exc:
        print(f"mutation_gap: bad ranges JSON: {exc}", file=sys.stderr)
        return 2
    source = Path(path).read_text(encoding="utf-8")
    for line in mutable_changed_lines(path, source, ranges):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
