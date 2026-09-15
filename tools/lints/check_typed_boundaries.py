#!/usr/bin/env python3
"""Touch-to-fix ratchet for untyped data crossing the API's boundaries.

Two things let a value's shape be guessed instead of known, and every one of
them is a bug that no type-checker can catch:

- ``TB001 loose-annotation`` -- a parameter or return annotated ``Any``,
  ``dict``, ``dict[str, Any]`` (or any annotation containing them). The
  function accepts or promises "some mapping", and every reader downstream
  has to guess its keys.
- ``TB002 string-key-read`` -- ``value.get("key")`` / ``value["key"]``. A
  string key is a guess about a shape; a typo compiles, a renamed field
  compiles, a key the producer never sets compiles. The shape belongs in a
  model, and the read in an attribute.

The debt predates the rule and is grandfathered per file in
``tools/lints/typed_boundaries_baseline.txt`` -- until a PR touches the file,
when its known violations must be fixed in that same PR (``_ratchet.py``).
A few modules ARE the boundary: they parse a raw document or provider
payload into a model exactly once, and string keys there are the point. They
are listed in ``BOUNDARY_MODULES`` with the reason, and nothing else is.

Usage::

    python3 tools/lints/check_typed_boundaries.py          # check (exits 1 on failure)
    python3 tools/lints/check_typed_boundaries.py --update # record the current baseline
    python3 tools/lints/check_typed_boundaries.py --count  # the debt, per rule and directory
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
import sys

from _common import iter_python_files
from _ratchet import REPO_ROOT, RatchetRule, run_ratchet

RULE = "typed-boundaries"
WHY = (
    "a dict[str, Any] signature or a value['key'] read lets a shape be guessed "
    "instead of declared; the debt is grandfathered per file only until a PR "
    "touches that file"
)
DOC = "tools/lints/README.md#typed-boundaries"

_HERE = Path(__file__).resolve().parent
BASELINE = _HERE / "typed_boundaries_baseline.txt"
APP_ROOT = REPO_ROOT / "apps" / "api" / "app"

LOOSE_ANNOTATION = "TB001"
STRING_KEY_READ = "TB002"

# The modules that parse raw data into models. String keys are legitimate
# exactly here, once, and the models they produce are what everything else
# reads. Keyed by path (a file, or a directory prefix ending in "/") relative
# to the repo root; every entry states why.
BOUNDARY_MODULES: dict[str, str] = {
    "apps/api/app/db/repositories/base.py": "the Mongo document -> model boundary",
    "apps/api/app/override/": "vendored overrides of third-party library internals",
    "apps/api/app/patches/": "monkeypatches of third-party library internals",
}

# Maps keyed by a protocol, not a shape: the key IS the contract (an HTTP
# header name, an environment variable), so reading it by string is honest.
PROTOCOL_MAPS = ("os.environ",)
PROTOCOL_MAP_ATTRIBUTES = ("headers", "query_params", "path_params", "cookies")

# A key read on a TypedDict is a declared shape, not a guess: mypy checks the key
# (apps/api/CLAUDE.md, Type Safety item 6). Repo TypedDicts are discovered from
# ``class X(TypedDict)``; these come from libraries and cannot be discovered.
EXTERNAL_TYPEDDICTS = ("ToolCall", "RunnableConfig")

_BASELINE_HEADER = """\
# typed-boundaries grandfather baseline.
# See tools/lints/check_typed_boundaries.py -- this is a TOUCH-TO-FIX ratchet,
# not a static exemption: a file listed here only stays quiet while untouched.
# The moment a PR modifies a listed file, its violations here must be fixed in
# that same PR, and this line deleted. New violations (new file, or a rule a
# file didn't already have) are never grandfathered by this list.
#
# One line per (file, rule), tab-separated, sorted. Regenerate with:
#   python3 tools/lints/check_typed_boundaries.py --update
#
# A line may carry a third field, "deferred-until=YYYY-MM-DD; <reason>", to
# keep a touched file's known violation from failing until that date (CI
# warns instead). Past the date it fails again: fix it, or renew the deferral
# with a fresh reason. --update keeps the field.
"""


def _is_loose(annotation: ast.expr) -> bool:
    """``Any`` anywhere, or a bare ``dict``/``Dict`` (``dict[str, int]`` is a shape)."""
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id == "Any":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            return True
    return _has_bare_dict(annotation)


def _has_bare_dict(annotation: ast.expr) -> bool:
    subscripted: set[int] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Subscript):
            subscripted.add(id(node.value))
    return any(
        isinstance(node, ast.Name) and node.id in ("dict", "Dict") and id(node) not in subscripted
        for node in ast.walk(annotation)
    )


def _loose_annotations(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = node.args
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if args.vararg:
            params.append(args.vararg)
        if args.kwarg:
            params.append(args.kwarg)
        for param in params:
            if param.annotation is not None and _is_loose(param.annotation):
                lines.append(param.annotation.lineno)
        if node.returns is not None and _is_loose(node.returns):
            lines.append(node.returns.lineno)
    return lines


def _is_protocol_map(receiver: ast.expr) -> bool:
    if ast.unparse(receiver) in PROTOCOL_MAPS:
        return True
    return isinstance(receiver, ast.Attribute) and receiver.attr in PROTOCOL_MAP_ATTRIBUTES


def _is_string_key_get(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and not _is_protocol_map(node.func.value)
    )


def _is_string_key_load(node: ast.AST) -> bool:
    """``value["key"]`` -- but ``Literal["key"]`` is a type, not a read."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and ast.unparse(node.value).split(".")[-1] != "Literal"
        and not _is_protocol_map(node.value)
    )


def _decorator_ids(tree: ast.AST) -> set[int]:
    """``@router.get("/path")`` is a route registration, not a read."""
    return {
        id(decorator)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        for decorator in node.decorator_list
    }


def typeddict_names(trees: list[ast.AST]) -> set[str]:
    """Every TypedDict class name in ``trees``, subclasses included, plus the external ones."""
    classes = [node for tree in trees for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    names = {"TypedDict", *EXTERNAL_TYPEDDICTS}
    grew = True
    while grew:
        found = {
            node.name
            for node in classes
            if node.name not in names and any(_base_name(base) in names for base in node.bases)
        }
        names |= found
        grew = bool(found)
    return names - {"TypedDict"}


def _base_name(base: ast.AST) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _names_typeddict(annotation: ast.expr, typeddicts: set[str]) -> bool:
    return any(_base_name(node) in typeddicts for node in ast.walk(annotation))


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Nodes lexically in ``scope``, stopping at nested functions (their own scopes)."""
    nodes: list[ast.AST] = []
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        pending: list[ast.AST] = [scope.args, *scope.body]
    elif isinstance(scope, ast.Lambda):
        pending = [scope.args, scope.body]
    else:
        pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        nodes.append(node)
        if not isinstance(node, _SCOPES):
            pending.extend(ast.iter_child_nodes(node))
    return nodes


def _rebound_names(nodes: list[ast.AST]) -> set[str]:
    return {node.arg for node in nodes if isinstance(node, ast.arg)} | {
        node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


def _typed_receivers(scope: ast.AST, typeddicts: set[str], inherited: set[str]) -> set[int]:
    """Ids of reads on TypedDict-bound names, each name resolved to its innermost binding scope."""
    nodes = _own_scope_nodes(scope)
    bound = (inherited - _rebound_names(nodes)) | _typeddict_bound_names(nodes, typeddicts)
    found: set[int] = set()
    for node in nodes:
        if isinstance(node, _SCOPES):
            found |= _typed_receivers(node, typeddicts, bound)
            continue
        receiver = _receiver(node)
        if isinstance(receiver, ast.Name) and receiver.id in bound:
            found.add(id(node))
    return found


def _typeddict_bound_names(nodes: list[ast.AST], typeddicts: set[str]) -> set[str]:
    """Names annotated with a TypedDict among ``nodes`` (parameters and annotated assignments)."""
    bound: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.arg) and node.annotation is not None:
            if _names_typeddict(node.annotation, typeddicts):
                bound.add(node.arg)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _names_typeddict(node.annotation, typeddicts)
        ):
            bound.add(node.target.id)
    return bound


def _receiver(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.value
    if isinstance(node, ast.Subscript):
        return node.value
    return None


def _string_key_reads(tree: ast.AST, typeddicts: set[str]) -> list[int]:
    decorators = _decorator_ids(tree)
    typed_receivers = _typed_receivers(tree, typeddicts, set())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call | ast.Subscript)
        and id(node) not in typed_receivers
        and ((_is_string_key_get(node) and id(node) not in decorators) or _is_string_key_load(node))
    ]


def scan(files: list[Path]) -> dict[tuple[str, str], list[int]]:
    """Every violating line per (file, rule), for the files given."""
    out: dict[tuple[str, str], list[int]] = {}
    parsed = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path)) for path in files
    }
    typeddicts = typeddict_names(list(parsed.values()))
    for path in files:
        relative = path.resolve().relative_to(REPO_ROOT).as_posix()
        if any(relative == entry or relative.startswith(entry) for entry in BOUNDARY_MODULES):
            continue
        tree = parsed[path]
        for rule, lines in (
            (LOOSE_ANNOTATION, _loose_annotations(tree)),
            (STRING_KEY_READ, _string_key_reads(tree, typeddicts)),
        ):
            if lines:
                out[(relative, rule)] = sorted(lines)
    return out


def _current_violations() -> dict[tuple[str, str], int]:
    return {key: lines[0] for key, lines in scan(iter_python_files([APP_ROOT])).items()}


def _print_count() -> None:
    found = scan(iter_python_files([APP_ROOT]))
    by_rule: Counter[str] = Counter()
    by_dir: Counter[tuple[str, str]] = Counter()
    for (path, rule), lines in found.items():
        by_rule[rule] += len(lines)
        by_dir[(rule, path.split("/")[3])] += len(lines)
    for rule in (LOOSE_ANNOTATION, STRING_KEY_READ):
        files = sum(1 for key in found if key[1] == rule)
        print(f"{rule}: {by_rule[rule]} in {files} files")
        for (r, directory), n in sorted(by_dir.items(), key=lambda kv: -kv[1]):
            if r == rule:
                print(f"  {directory:<14} {n}")


_RATCHET = RatchetRule(
    name=RULE,
    why=WHY,
    doc=DOC,
    baseline=BASELINE,
    header=_BASELINE_HEADER,
    script="tools/lints/check_typed_boundaries.py",
    fix_new=(
        "declare the shape: a Pydantic model (or TypedDict for an in-process "
        "record) instead of dict[str, Any]/Any, and read its attribute instead of a string key"
    ),
)


def main(argv: list[str]) -> int:
    if "--count" in argv:
        _print_count()
        return 0
    return run_ratchet(_RATCHET, _current_violations(), argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
