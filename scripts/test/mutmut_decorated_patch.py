"""Allow mutmut to mutate decorated functions (FastAPI endpoints, @Cacheable, ...).

mutmut 3.7.0 skips EVERY FunctionDef with decorators (file_mutation.py
``_skip_node_and_children``). The stated reasons:

1. "copying them for the trampoline setup can cause side effects" — the
   mutants file re-executes decorators at import (e.g. ``@router.get``
   registers the trampoline on the router). That registration is exactly
   what the mutation run needs: the module under test IS the mutants file,
   and its own decorator stack wraps the trampoline (the trampoline
   decorator is inserted BELOW the existing decorators), so calls flow
   router -> Cacheable -> trampoline -> original/mutant. Verified: the
   trampoline wrapper is decorator-agnostic (handles sync/async/generator).
2. "decorators are executed when the function is defined, so we don't want
   to mutate their arguments" — REAL: mutating ``@Cacheable(ttl=...)`` args
   could raise at import. Fixed here by skipping ``cst.Decorator`` nodes
   entirely: the function body mutates, the decorator expressions never do.
3. "@property decorators break the trampoline signature assignment" — REAL:
   kept — functions whose first decorator is ``property`` are still skipped.

This module monkeypatches the visitor; mutation.sh loads it into the mutmut
process via PYTHONPATH before ``mutmut run``. The reimplementation mirrors
mutmut 3.7.0's method EXACTLY (pinned in uv.lock) with only the
decorated-function branch changed.
"""

from __future__ import annotations

import libcst as cst
from libcst.metadata import PositionProvider
from mutmut.mutation.file_mutation import (
    NEVER_MUTATE_FUNCTION_CALLS,
    NEVER_MUTATE_FUNCTION_NAMES,
    MutationVisitor,
)


def _skip_node_and_children(self: MutationVisitor, node: cst.CSTNode) -> bool:
    position = self.get_metadata(PositionProvider, node, None)
    if position and position.start.line in self._ignored_node_lines:
        if isinstance(node, cst.ClassDef):
            self.ignored_classes.add(node.name.value)
            return True
        if isinstance(node, cst.FunctionDef):
            self.ignored_functions.add(node.name.value)
            return True
        # other types of nodes (if, elif, for, while, ...) get treated on a line-by-line basis

    if position and position.start.line in self._ignored_pattern_lines:
        if isinstance(node, cst.BaseExpression):
            return True

    if (
        isinstance(node, cst.Call)
        and isinstance(node.func, cst.Name)
        and node.func.value in NEVER_MUTATE_FUNCTION_CALLS
    ) or (isinstance(node, cst.FunctionDef) and node.name.value in NEVER_MUTATE_FUNCTION_NAMES):
        return True

    # ignore everything inside of type annotations
    if isinstance(node, cst.Annotation):
        return True

    # default args are executed at definition time
    # We want to prevent e.g. def foo(x = abs(-1)) mutating to def foo(x = abs(None)),
    # which would raise an Exception as soon as the function is defined (can break the whole import)
    # Therefore we only allow simple default values, where mutations should not raise exceptions
    if (
        isinstance(node, cst.Param)
        and node.default
        and not isinstance(node.default, (cst.Name, cst.BaseNumber, cst.BaseString))
    ):
        return True

    # --- patched branch: decorated functions are mutation targets ---
    # Never mutate decorator expressions: they execute at import time, so a
    # mutated argument (e.g. @Cacheable(ttl=...)) could raise before any
    # test runs. The decorated function itself IS a mutation target.
    if isinstance(node, cst.Decorator):
        return True

    if isinstance(node, cst.FunctionDef) and node.decorators:
        first = node.decorators[0].decorator
        if isinstance(first, cst.Name):
            # @property breaks the trampoline's signature assignment.
            if first.value == "property":
                return True
            # @staticmethod/@classmethod: original already allowed these.
            if len(node.decorators) == 1 and first.value in ("staticmethod", "classmethod"):
                return False
        return False

    if isinstance(node, cst.ClassDef) and len(node.decorators):
        return True

    return False


MutationVisitor._skip_node_and_children = _skip_node_and_children
