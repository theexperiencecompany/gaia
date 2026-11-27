#!/usr/bin/env python3
"""Run interrogate, counting a function its @with_doc(...) decorator documents as documented.

Tool functions take their docstring at import time from app/templates/docstrings
(app.decorators.with_doc), so the source holds none for interrogate's AST to see.
Arguments are interrogate's own: python3 tools/lints/docstring_coverage.py -c pyproject.toml [paths]
"""

from __future__ import annotations

import ast

from interrogate import cli, visit

WITH_DOC_DECORATOR = "with_doc"
# Read before main() swaps the class, so the subclass's check never calls itself.
_interrogate_has_doc = visit.CoverageVisitor._has_doc


def documented_by_decorator(node: ast.AST) -> bool:
    """Return whether node carries a @with_doc(...) call among its decorators."""
    for decorator in getattr(node, "decorator_list", ()):
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name == WITH_DOC_DECORATOR:
            return True
    return False


class WithDocCoverageVisitor(visit.CoverageVisitor):
    """interrogate's visitor, plus @with_doc as a docstring."""

    @staticmethod
    def _has_doc(node: ast.AST) -> bool:
        return bool(_interrogate_has_doc(node)) or documented_by_decorator(node)


def main() -> None:
    """Swap in the @with_doc-aware visitor, then hand the command line to interrogate."""
    # interrogate.coverage builds its visitor through this module attribute on every file.
    visit.CoverageVisitor = WithDocCoverageVisitor
    cli.main(prog_name="interrogate")


if __name__ == "__main__":
    main()
