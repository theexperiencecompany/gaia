"""Behaviour tests for tools/lints/docstring_coverage.py, run as CI runs it: a subprocess on real files."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parent / "docstring_coverage.py"

TOOL_MODULE = '''\
"""A tool module."""

from app.decorators import with_doc
from app import decorators
from app.templates.docstrings import TOOL_DOC


@tool
@with_doc(TOOL_DOC)
async def decorated_tool(query: str) -> str:
    return query


@decorators.with_doc(TOOL_DOC)
def attribute_decorated(query: str) -> str:
    return query


def documented(query: str) -> str:
    """Return query."""
    return query


def undocumented(query: str) -> str:
    return query


@with_doc
def bare_decorator_is_not_a_docstring(query: str) -> str:
    return query
'''


def _report(tmp_path: Path) -> dict[str, str]:
    module = tmp_path / "tool_module.py"
    module.write_text(TOOL_MODULE)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "-vv", "--fail-under", "0", "--no-color", str(module)],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    rows = [line.strip("| ").split("|") for line in result.stdout.splitlines() if " (L" in line]
    return {name.split(" (L")[0].strip(): status.strip() for name, status in rows}


def test_a_with_doc_function_counts_as_documented(tmp_path: Path) -> None:
    report = _report(tmp_path)

    assert report["decorated_tool"] == "COVERED"
    assert report["attribute_decorated"] == "COVERED"


def test_a_function_with_neither_a_docstring_nor_with_doc_is_still_missed(tmp_path: Path) -> None:
    report = _report(tmp_path)

    assert report["documented"] == "COVERED"
    assert report["undocumented"] == "MISSED"
    assert report["bare_decorator_is_not_a_docstring"] == "MISSED"
