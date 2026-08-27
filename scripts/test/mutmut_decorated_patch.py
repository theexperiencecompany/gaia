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


# mutmut's stack walk resolves every caller frame with
# `Path(filename).resolve(strict=True)` to decide whether the frame is user
# code. CPython synthesises frames whose `co_filename` is a bracketed
# pseudo-path — `<frozen importlib._bootstrap>` for the import machinery,
# `<string>` for exec'd code — and strict resolution raises FileNotFoundError
# on those. A module that calls one of its own mutated functions at IMPORT
# time is entered from exactly such a frame: `app/decorators/rate_limiting.py`
# is imported by `bash_tool.py`, which applies `@with_rate_limiting(...)` at
# module level. The stats phase then dies before a single test runs and the
# whole module goes unmeasured.
#
# A pseudo-frame is by definition not user code, and user-code frames are the
# only thing the walk counts — so skipping it is the semantics mutmut already
# wants, minus the crash. The body below mirrors mutmut 3.7.0's
# `record_trampoline_hit` exactly (pinned in uv.lock) with only that guard
# added; `trampoline.py` binds the name at import, so both bindings are
# rebound.
import inspect as _inspect
from pathlib import Path as _Path

import mutmut as _mutmut
from mutmut import __main__ as _mutmut_main
from mutmut.configuration import Config as _Config
from mutmut.mutation import trampoline as _trampoline_mod
from mutmut.state import state as _state

# filename -> "is this frame inside a mutated source path". Keyed on the raw
# co_filename, so it also short-circuits the resolve() itself.
_USER_CODE_CACHE: dict[str, bool] = {}


def _patched_record_trampoline_hit(name: str, caller: str | None = None) -> None:
    assert not name.startswith("src."), (
        "Failed trampoline hit. Module name starts with `src.`, which is invalid"
    )

    mutated_source_paths = _Config.get().resolved_mutated_source_paths

    if _Config.get().max_stack_depth != -1:
        f = _inspect.currentframe()
        c = _Config.get().max_stack_depth
        while c and f:
            filename = f.f_code.co_filename
            f = f.f_back
            if "pytest" in filename or "hammett" in filename or "unittest" in filename:
                break
            # --- patched guard: synthetic frames are not user code ---
            if filename.startswith("<") and filename.endswith(">"):
                continue
            # --- patched: memoise the answer per filename ---
            # Upstream calls Path(filename).resolve(strict=True) here, which is
            # a SYSCALL, and this runs for every stack frame of every
            # trampolined call — millions of times in a test that exercises a
            # mutated function in a loop. The set of filenames is tiny and
            # mutated_source_paths is fixed for the run, so the whole question
            # is answerable once per file. On a laptop with a warm page cache
            # the difference hides; on a CI runner it is the difference between
            # app/decorators/rate_limiting.py taking 18 seconds and being
            # killed at a 35-minute cap.
            is_user_code = _USER_CODE_CACHE.get(filename)
            if is_user_code is None:
                file_path = _Path(filename).resolve(strict=True)
                is_user_code = any(path in file_path.parents for path in mutated_source_paths)
                _USER_CODE_CACHE[filename] = is_user_code
            if is_user_code:
                # only include stack frames of user-code; exclude mutmut and 3rd library stack frames
                c -= 1

        if not c:
            return

    _mutmut._stats.add(name)
    if caller is not None and _Config.get().track_dependencies:
        _state().function_dependencies[name].add(caller)


_mutmut_main.record_trampoline_hit = _patched_record_trampoline_hit
_trampoline_mod.record_trampoline_hit = _patched_record_trampoline_hit
