"""The canonical wide-event field schema, read live from ``wide_events.py``.

The ``context`` rule checks that handlers set fields the dashboards can query,
which means fields declared on ``WideEventFields``. Parsing the schema instead
of hardcoding it keeps the map honest as the schema evolves — a new namespace
TypedDict is recognized the moment it lands.
"""

from __future__ import annotations

import ast
from pathlib import Path

WIDE_EVENTS_MODULE = Path("libs/shared/py/wide_events.py")
_SCHEMA_CLASS = "WideEventFields"


def canonical_fields(repo_root: Path) -> frozenset[str]:
    """Field names declared on ``WideEventFields`` (namespaces + top-level keys)."""
    module_path = repo_root / WIDE_EVENTS_MODULE
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == _SCHEMA_CLASS:
            fields = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
            if not fields:
                raise ValueError(f"{_SCHEMA_CLASS} in {module_path} declares no fields")
            return frozenset(fields)
    raise ValueError(f"{_SCHEMA_CLASS} not found in {module_path}")
