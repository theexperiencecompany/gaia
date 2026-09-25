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
from typing import Literal

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
    "apps/api/app/browser_host/cdp_mux.py": "the CDP wire: Chrome owns every command and result shape",
    "apps/api/app/browser_host/chromium.py": "the CDP wire: Chrome owns every command and result shape",
    "apps/api/app/browser_host/proxy.py": "the CDP wire: Chrome owns every command and result shape",
    "apps/api/app/browser_host/screencast.py": "the CDP wire: Chrome owns every command and result shape",
}

# Maps keyed by a protocol, not a shape: the key IS the contract (an HTTP
# header name, an environment variable), so reading it by string is honest.
PROTOCOL_MAPS = ("os.environ",)
PROTOCOL_MAP_ATTRIBUTES = ("headers", "query_params", "path_params", "cookies")

# A key read on a TypedDict is a declared shape, not a guess: mypy checks the key
# (apps/api/CLAUDE.md, Type Safety item 6). Repo TypedDicts are discovered from
# ``class X(TypedDict)``; these come from libraries and cannot be discovered.
EXTERNAL_TYPEDDICTS = (
    "ToolCall",
    "InvalidToolCall",
    "RunnableConfig",
    "UsageMetadata",
    "InputTokenDetails",
    "OutputTokenDetails",
    "StorageState",
    "StorageStateCookie",
)
# Library TypedDicts app classes subclass, by the path they are imported from: the
# local name is often an alias (``State as _BigtoolState``), so the bare name can't
# be listed. Each is verified with typing_extensions.is_typeddict.
EXTERNAL_TYPEDDICT_PATHS = frozenset(
    {
        "langgraph_bigtool.graph.State",
        "langgraph.graph.MessagesState",
        "langgraph.graph.message.MessagesState",
        "langchain.agents.AgentState",
        "langchain.agents.middleware.types.AgentState",
        "chromadb.GetResult",
        "chromadb.QueryResult",
        "chromadb.api.types.GetResult",
        "chromadb.api.types.QueryResult",
        "langchain_core.messages.ReasoningContentBlock",
        "langchain_core.messages.content.ReasoningContentBlock",
        "composio.core.models.tools.ToolExecutionResponse",
        "cdp_use.cdp.dom.commands.ResolveNodeReturns",
        "cdp_use.cdp.domsnapshot.commands.CaptureSnapshotReturns",
        "cdp_use.cdp.domsnapshot.types.DocumentSnapshot",
        "cdp_use.cdp.domsnapshot.types.NodeTreeSnapshot",
        "cdp_use.cdp.domsnapshot.types.RareBooleanData",
        "cdp_use.cdp.domsnapshot.types.RareStringData",
        "cdp_use.cdp.page.commands.CaptureScreenshotReturns",
        "cdp_use.cdp.runtime.commands.CallFunctionOnReturns",
        "cdp_use.cdp.runtime.commands.EvaluateReturns",
        "cdp_use.cdp.runtime.types.RemoteObject",
    }
)
# Collections whose one type argument is the element a loop over them yields.
TYPED_COLLECTIONS = ("list", "Sequence", "Iterable", "set", "frozenset")
# Mappings whose second type argument is what .values() / .items() yield as the value.
TYPED_MAPPINGS = ("dict", "Mapping")

#: How a loop reaches a container's TypedDict elements: directly, or via .values()/.items().
ContainerKind = Literal["sequence", "mapping"]

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
    names = {"TypedDict", *EXTERNAL_TYPEDDICTS, *_imported_external_typeddicts(trees)}
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


def _imported_external_typeddicts(trees: list[ast.AST]) -> set[str]:
    """Local names bound by ``from M import N [as A]`` where ``M.N`` is a listed library TypedDict."""
    return {
        alias.asname or alias.name
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
        if f"{node.module}.{alias.name}" in EXTERNAL_TYPEDDICT_PATHS
    }


def _base_name(base: ast.AST) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _names_typeddict(annotation: ast.expr, typeddicts: set[str]) -> bool:
    return any(_base_name(node) in typeddicts for node in ast.walk(annotation))


# Comprehensions are scopes too (Python 3): a target bound in one never rebinds a sibling's.
_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


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


def _typed_receivers(
    scope: ast.AST,
    typeddicts: set[str],
    inherited: set[str],
    inherited_containers: dict[str, ContainerKind],
) -> set[int]:
    """Ids of reads on TypedDict-bound names, each name resolved to its innermost binding scope."""
    nodes = _own_scope_nodes(scope)
    rebound = _rebound_names(nodes)
    containers = {
        name: kind for name, kind in inherited_containers.items() if name not in rebound
    } | _typeddict_container_names(nodes, typeddicts)
    bound = (
        (inherited - rebound)
        | _typeddict_bound_names(nodes, typeddicts)
        | _typed_loop_targets(nodes, containers)
    )
    found: set[int] = set()
    for node in nodes:
        if isinstance(node, _SCOPES):
            found |= _typed_receivers(node, typeddicts, bound, containers)
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


def _without_none(annotation: ast.expr) -> ast.expr:
    """Strip the None arm of ``X | None`` / ``Optional[X]``; anything else is returned as-is."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        arms = [
            arm
            for arm in (annotation.left, annotation.right)
            if not (isinstance(arm, ast.Constant) and arm.value is None)
        ]
        return arms[0] if len(arms) == 1 else annotation
    if isinstance(annotation, ast.Subscript) and _base_name(annotation.value) == "Optional":
        return annotation.slice
    return annotation


def _typeddict_container(annotation: ast.expr, typeddicts: set[str]) -> ContainerKind | None:
    """Classify a collection (``tuple[T, ...]`` included) or mapping annotation whose element is a TypedDict."""
    annotation = _without_none(annotation)
    if not isinstance(annotation, ast.Subscript):
        return None
    container = _base_name(annotation.value)
    elts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else []
    element: ast.expr | None = None
    kind: ContainerKind = "sequence"
    if container in TYPED_COLLECTIONS:
        element = annotation.slice
    elif container == "tuple" and len(elts) == 2:
        if isinstance(elts[1], ast.Constant) and elts[1].value is Ellipsis:
            element = elts[0]
    elif container in TYPED_MAPPINGS and len(elts) == 2:
        element, kind = elts[1], "mapping"
    if isinstance(element, ast.Name | ast.Attribute) and _base_name(element) in typeddicts:
        return kind
    return None


def _typeddict_container_names(
    nodes: list[ast.AST], typeddicts: set[str]
) -> dict[str, ContainerKind]:
    """Names annotated as a collection or mapping of TypedDicts among ``nodes``."""
    names: dict[str, ContainerKind] = {}
    for node in nodes:
        if isinstance(node, ast.arg) and node.annotation is not None:
            if kind := _typeddict_container(node.annotation, typeddicts):
                names[node.arg] = kind
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if kind := _typeddict_container(node.annotation, typeddicts):
                names[node.target.id] = kind
    return names


def _typeddict_loop_target(
    loop: ast.For | ast.AsyncFor | ast.comprehension, containers: dict[str, ContainerKind]
) -> ast.Name | None:
    """Return the name a loop binds to a TypedDict element: x in seq, v in m.values(), k, v in m.items()."""
    iterated = loop.iter
    if isinstance(iterated, ast.Name):
        if containers.get(iterated.id) == "sequence" and isinstance(loop.target, ast.Name):
            return loop.target
        return None
    if not (
        isinstance(iterated, ast.Call)
        and not iterated.args
        and isinstance(iterated.func, ast.Attribute)
        and isinstance(iterated.func.value, ast.Name)
        and containers.get(iterated.func.value.id) == "mapping"
    ):
        return None
    target = loop.target
    if iterated.func.attr == "values" and isinstance(target, ast.Name):
        return target
    if (
        iterated.func.attr == "items"
        and isinstance(target, ast.Tuple)
        and len(target.elts) == 2
        and isinstance(target.elts[1], ast.Name)
    ):
        return target.elts[1]
    return None


def _typed_loop_targets(nodes: list[ast.AST], containers: dict[str, ContainerKind]) -> set[str]:
    """Loop/comprehension targets bound to a TypedDict element that nothing else rebinds."""
    targets = [
        target
        for node in nodes
        if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension)
        and (target := _typeddict_loop_target(node, containers)) is not None
    ]
    target_ids = {id(target) for target in targets}
    stored_elsewhere = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
        and id(node) not in target_ids
    }
    return {target.id for target in targets} - stored_elsewhere


def _receiver(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.value
    if isinstance(node, ast.Subscript):
        return node.value
    return None


def _string_key_reads(tree: ast.AST, typeddicts: set[str]) -> list[int]:
    decorators = _decorator_ids(tree)
    typed_receivers = _typed_receivers(tree, typeddicts, set(), {})
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
