"""Load a suite's cases from its YAML data directory.

One loader, shared by every suite that keeps its ground truth in
``data/<suite>/*.yaml``. Files are read in filename order and case ids must be
unique across the whole directory — a duplicate id silently shadows a case in
the journal and the Opik trace key, so it fails loud here instead.

Known debt: ``suites/quality.py`` and ``suites/capability.py`` predate this and
carry their own near-identical loaders (quality folds unknown top-level keys into
``setup``, capability reads an explicit ``setup:`` block). They should converge
on this function; this file is the target shape — an explicit ``setup:`` block,
because "whatever keys I didn't recognise" is not a schema.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .gates import ExtraGates, validate_gates
from .scorers import validate_tool_expectations
from .types import Case


def load_case_files(
    data_dir: Path, suite: str, extra_gates: ExtraGates | None = None
) -> list[Case]:
    """Every case defined under ``data_dir``, validated and id-unique.

    ``extra_gates`` names the gates the calling suite implements beyond the
    shared set, so a gate name nothing can score dies here rather than being
    read back as 0.0 at verdict time and reported as an agent failure.
    """
    cases: list[Case] = []
    seen: dict[str, str] = {}
    for path in sorted(data_dir.glob("*.yaml")):
        rows = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"{suite} data {path.name}: expected a YAML list of cases")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{suite} data {path.name}: case is not a mapping")
            case_id = str(row["id"])
            expected = row.get("expected")
            if not isinstance(expected, dict):
                raise ValueError(f"{suite} case {case_id}: 'expected' must be a mapping")
            validate_tool_expectations(case_id, expected)
            if case_id in seen:
                raise ValueError(
                    f"{suite}: duplicate case id {case_id!r} in {path.name} "
                    f"(already defined in {seen[case_id]})"
                )
            seen[case_id] = path.name
            setup = row.get("setup") or {}
            if not isinstance(setup, dict):
                raise ValueError(f"{suite} case {case_id}: 'setup' must be a mapping")
            case = Case(
                id=case_id,
                ticket=str(row.get("ticket") or ""),
                prompt=str(row.get("prompt") or ""),
                expected=expected,
                tags=[str(tag) for tag in (row.get("tags") or [])],
                setup=setup,
            )
            validate_gates(suite, case.id, case.gates, extra_gates)
            cases.append(case)
    if not cases:
        raise ValueError(f"{suite}: no cases found in {data_dir}")
    return cases
