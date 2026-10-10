"""Scope mutant GENERATION to the PR's changed lines.

mutmut has no "mutate only these lines" CLI flag, but it does have the
mechanism: ``create_mutations(..., covered_lines=...)`` drops every node whose
start line is outside the set, and ``mutmut._covered_lines`` is the global
mutmut fills in for its own ``mutate_only_covered_lines`` feature. This module
fills that global from the diff instead of from a coverage pass, which is the
same filter without the extra full-suite run (that feature stays off — see
``[tool.mutmut]`` in apps/api/pyproject.toml).

It replaces stamping ``# pragma: no mutate`` onto every unchanged source line,
which only ever half-worked: mutmut resolves a trailing pragma to the START line
of the statement it terminates, so on a multi-line statement — most statements
here — every node after the first line stayed a mutation target. Measured on
app/helpers/agent_helpers.py (933 lines, 54 changed): 504 mutants unscoped, 228
with the pragma stamping, 41 with this. The lane was spending its 30-minute
budget generating and testing mutants the classifier then discarded as
UNCHANGED, and timing out before it finished.

Loaded into the mutmut process by mutation.sh via PYTHONPATH, alongside
mutmut_decorated_patch. With no env vars set it does nothing, so a bare
``bash scripts/ci/mutation.sh module app/x.py`` still mutates the whole module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import warnings

import mutmut
from mutmut import __main__ as mutmut_main

#: Compact JSON ``[[start, end], ...]`` of the module's changed line ranges.
RANGES_ENV = "MUTMUT_CHANGED_RANGES"
#: The module those ranges belong to, repo-relative as mutmut walks it.
MODULE_ENV = "MUTMUT_SCOPED_MODULE"


def _serial_create_mutants(_max_children: int) -> mutmut_main.MutantGenerationStats:
    """``create_mutants`` without the process pool.

    mutmut generates mutants in a ``multiprocessing.Pool``, and the workers only
    inherit ``_covered_lines`` under the fork start method — so the scoping would
    apply on Linux CI and silently not on macOS (spawn). A run mutates exactly
    one file (``source_paths`` is the single module under test), so the pool wins
    nothing and dropping it makes the scoping platform-independent.

    ``_max_children`` sizes that pool and is therefore unused here; mutmut passes
    it positionally, so the name is free to say so.

    Mirrors mutmut 3.7.0's own body; only the pool is gone.
    """
    stats = mutmut_main.MutantGenerationStats()
    for path in mutmut_main.walk_source_files():
        result = mutmut_main.create_file_mutants(path)
        for warning in result.warnings:
            warnings.warn(warning, stacklevel=2)
        if result.error:
            raise result.error
        if result.unmodified:
            stats.unmodified += 1
        elif result.ignored:
            stats.ignored += 1
        else:
            stats.mutated += 1
        if result.current_hashes:
            mutmut_main.state().current_function_hashes.update(result.current_hashes)
    return stats


def apply() -> None:
    raw_ranges, module = os.environ.get(RANGES_ENV), os.environ.get(MODULE_ENV)
    if not raw_ranges or not module:
        return
    ranges = json.loads(raw_ranges)
    if not ranges:
        return

    # The key must match what mutmut looks up: code_coverage builds it as the
    # absolute path of the file inside the mutants/ tree.
    key = str((Path("mutants") / module).absolute())
    mutmut._covered_lines = {key: {line for start, end in ranges for line in range(start, end + 1)}}
    mutmut_main.create_mutants = _serial_create_mutants


apply()
