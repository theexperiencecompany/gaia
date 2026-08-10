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
        first_name = (
            first.value
            if isinstance(first, cst.Name)
            else first.func.value
            if isinstance(first, cst.Call) and isinstance(first.func, cst.Name)
            else None
        )
        if first_name is not None:
            # @property breaks the trampoline's signature assignment.
            if first_name == "property":
                return True
            # @staticmethod/@classmethod: original already allowed these.
            if len(node.decorators) == 1 and first_name in ("staticmethod", "classmethod"):
                return False
        return False

    if isinstance(node, cst.ClassDef) and len(node.decorators):
        return True

    return False


MutationVisitor._skip_node_and_children = _skip_node_and_children


# Decorated functions: mutmut copies the function's decorators onto the
# mangled ORIGINAL and every MUTANT too (function_trampoline_arrangement
# reuses the full FunctionDef node). Re-executing decorators there is
# harmful — @lazy_provider REBINDS the mangled name to its register_provider
# closure (so the trampoline's dict picks up the wrong orig), and
# @lru_cache creates a second cache layer the tests cannot clear. The
# trampoline is the only entry point that should wear the decorators.
#
# Exception: @classmethod and @staticmethod MUST stay on the copies.
# mutmut's own trampoline handles them specially (is_classmethod=True:
# getattr(cls, mangled_orig) must return the class-BOUND method, and the
# trampoline slices args[1:] because cls arrives bound). Stripping the
# decorator leaves a plain function in the class dict, getattr returns it
# UNBOUND, and every call through the trampoline dies with "missing
# positional argument" (observed on composio_schemas.github_tools). They
# are also harmless to re-execute — which is why mutmut's original skip
# logic (`len(decorators) == 1 and name in ("staticmethod", "classmethod")`)
# allows them as mutation targets in the first place.
import libcst as _cst
from mutmut.mutation import file_mutation as _file_mutation

_orig_arrange = _file_mutation.function_trampoline_arrangement

_REEXECUTE_SAFE_DECORATORS = ("classmethod", "staticmethod")


def _patched_arrange(function, mutants, class_name):
    decls, method_nodes, assignments, names = _orig_arrange(function, mutants, class_name)
    fixed = [method_nodes[0]]
    for node in method_nodes[1:]:
        if isinstance(node, _cst.FunctionDef):
            keep = []
            if len(node.decorators) == 1:
                decorator = node.decorators[0].decorator
                if (
                    isinstance(decorator, _cst.Name)
                    and decorator.value in _REEXECUTE_SAFE_DECORATORS
                ):
                    keep = list(node.decorators)
            node = node.with_changes(decorators=keep)
        fixed.append(node)
    return decls, fixed, assignments, names


_file_mutation.function_trampoline_arrangement = _patched_arrange


# The covered-lines coverage pass unloads EVERY module imported during the
# stats run (mutmut.code_coverage._unload_modules_not_in), so the mutant
# runs re-import them. C extensions (numpy, PyO3) cannot be re-imported in
# one process, and pydantic/mcp_use class registries break on re-definition
# (KeyError: 'pydantic.root_model'). The unload only needs to drop the
# modules the mutants file REPLACES — those live in the mutants tree.
# Site-packages modules never change between phases, so skipping them is
# safe and fixes the whole class.
import importlib as _importlib
import sys as _sys

from mutmut import code_coverage as _code_coverage

_orig_unload = _code_coverage._unload_modules_not_in


def _patched_unload(modules: dict) -> None:
    for name in list(_sys.modules):
        if name == "mutmut.code_coverage":
            continue
        if name not in modules:
            module = _sys.modules[name]
            module_file = getattr(module, "__file__", "")
            if module_file and "/mutants/" in module_file:
                _sys.modules.pop(name, None)
    _importlib.invalidate_caches()


_code_coverage._unload_modules_not_in = _patched_unload
