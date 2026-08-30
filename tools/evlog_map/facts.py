"""Single-pass AST facts per file — everything the rules need, extracted once.

Mirrors evlog's ``facts.ts``: rules never walk the AST themselves; they read
the reduced facts. A handler's facts cover its *own scope only* (stopping at
nested functions/classes/lambdas), matching the semantics of the
``route-contract`` lint so the two tools never disagree about what counts.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
# FastAPI's imperative registration — the exact equivalent of the decorators.
ROUTE_REGISTRARS = frozenset({"add_api_route", "add_api_websocket_route"})
DEFAULT_REGISTRAR_METHOD = "get"  # FastAPI's default when `methods=` is omitted
WIDE_EVENT_SETTERS = frozenset({"set", "set_ns"})
EVENT_RECORDING_METHODS = frozenset({"warning", "error", "exception", "critical", "audit"})
BOUNDARY_CALLS = frozenset({"wide_task", "log_context"})
WRITE_CALLS = frozenset({"create", "update", "insert", "upsert"})


@dataclass(frozen=True)
class ExceptFact:
    """One ``except`` clause: whether it swallows the error silently."""

    line: int
    is_empty: bool
    handled: bool  # records the error on the event, or re-raises it intact


@dataclass(frozen=True)
class RaiseFact:
    """One ``raise`` statement and what it raises."""

    line: int
    callee: str | None  # exception constructor name, None for bare re-raise
    has_detail: bool  # HTTPException(..., detail=...) style
    is_bare: bool  # bare ``raise`` inside an except clause


@dataclass(frozen=True)
class LogCallFact:
    """One ``log.<method>(...)`` message call."""

    line: int
    method: str
    has_kwargs: bool
    msg_is_fstring: bool


@dataclass
class HandlerFacts:
    """Facts about one entry point's own scope."""

    name: str
    line: int
    deco_line: int  # first decorator's line; suppressions may sit above it
    kind: str  # "api" | "websocket" | "worker" | "voice"
    methods: tuple[str, ...]
    route_path: str
    # Every registered path — a handler can stack several route decorators
    # (health.py registers "/", "/ping", "/health", …), and exemption must
    # look at all of them, not just the first.
    route_paths: tuple[str, ...] = ()
    sets_wide_event: bool = False
    set_field_names: set[str] = field(default_factory=set)
    calls_audit: bool = False
    has_boundary: bool = False
    excepts: list[ExceptFact] = field(default_factory=list)
    raises: list[RaiseFact] = field(default_factory=list)
    log_calls: list[LogCallFact] = field(default_factory=list)


@dataclass
class FileFacts:
    """Facts about one Python file."""

    path: Path
    imports: set[str] = field(default_factory=set)  # top-level module names
    # Everything in front of a decorator's path: where the app mounts this
    # file's router plus the router's own ``APIRouter(prefix=…)``.
    router_prefix: str = ""
    handlers: list[HandlerFacts] = field(default_factory=list)
    names: set[str] = field(default_factory=set)  # identifiers/attributes seen
    has_write_calls: bool = False


def _iter_own_scope(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """The handler's own nodes, stopping at nested scopes (route-contract semantics)."""
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        out.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.append(child)
    return out


def _iter_nested(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Every node in the handler, nested function bodies included.

    ``_iter_own_scope`` stops at nested scopes because the route-contract checks
    score the handler's own body. Boundary detection is different: a boundary
    inside a nested helper (an SSE generator, a ``asyncio.create_task`` coroutine
    defined inline, a websocket relay) is a real wide-event boundary — the JS
    scanner credits nested inline functions the same way (the bots scanner in
    scripts/ci/lib/evlog-map-bots.mjs: ``analyzeBody`` recurses via
    ``ts.forEachChild``). Converging the two keeps a
    boundary that lives in a nested scope from being invisible here.
    """
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _route_decorators(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    """Every ``(method, path)`` the function is registered under.

    Matches any ``@<name>.<verb>`` receiver, mirroring the route-contract
    lint, and collects ALL stacked route decorators — a handler registered
    under five paths is one entry point with five paths.
    """
    routes: list[tuple[str, str]] = []
    for deco in func.decorator_list:
        call = deco if isinstance(deco, ast.Call) else None
        target = call.func if call else deco
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
            continue
        if target.attr in HTTP_METHODS or target.attr == "websocket":
            path = ""
            if call and call.args and isinstance(call.args[0], ast.Constant):
                if isinstance(call.args[0].value, str):
                    path = call.args[0].value
            routes.append((target.attr, path))
    return routes


def _registered_routes(tree: ast.Module) -> dict[str, list[tuple[str, str]]]:
    """``(method, path)`` per endpoint function registered imperatively.

    ``router.add_api_route("/x", handler, methods=["POST"])`` is exactly what
    ``@router.post("/x")`` compiles down to, and FastAPI serves the two
    identically — so discovery must see both. Otherwise rewriting a route into
    the imperative form deletes it from the map, and losing an unscored entry
    point *raises* the score: the refactor reads as an improvement.
    """
    routes: dict[str, list[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not (isinstance(target, ast.Attribute) and target.attr in ROUTE_REGISTRARS):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Name):
            continue
        path = ""
        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            path = node.args[0].value
        if target.attr == "add_api_websocket_route":
            methods = ["websocket"]
        else:
            methods = [DEFAULT_REGISTRAR_METHOD]
            for kw in node.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                    methods = [
                        elt.value.lower()
                        for elt in kw.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
        routes.setdefault(node.args[1].id, []).extend((method, path) for method in methods)
    return routes


def repo_relative(path: Path) -> str:
    """The path from the monorepo anchor down — never the absolute prefix.

    Used for sensitivity terms and for baseline matching: an absolute prefix
    belongs to the machine, not the repo (a CI worktree named ``base-checkout``
    once classified every file as money), and base-worktree paths must compare
    equal to their in-repo counterparts.
    """
    parts = path.parts
    for anchor in ("apps", "libs"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    return path.name


def _log_attr(node: ast.Call, log_aliases: frozenset[str]) -> str | None:
    """The ``<method>`` of a ``log.<method>(...)`` call (any import alias), else None."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id in log_aliases:
            return func.attr
    return None


def _wide_event_log_aliases(tree: ast.Module) -> frozenset[str]:
    """Names the wide-event logger is bound to in this file.

    ``log`` by convention, but a handful of files import it as ``wide_log`` /
    ``logger`` — missing those would report instrumented handlers as dark.
    """
    aliases = {"log"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("wide_events"):
            for alias in node.names:
                if alias.name == "log":
                    aliases.add(alias.asname or alias.name)
    return frozenset(aliases)


def _call_name(node: ast.expr) -> str | None:
    """Constructor/function name of a call or name expression."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _preserves_caught_error(node: ast.Raise, bound_name: str | None) -> bool:
    """Whether a ``raise`` inside an except clause keeps the caught exception.

    A bare ``raise`` re-raises it; ``raise <name>`` re-raises the same object;
    ``raise New(...) from <name>`` sets ``__cause__``, which the app's exception
    handler reads. ``raise New(...)`` with no ``from`` — and ``from None``,
    which deletes the cause on purpose — destroy the type and message of what
    actually failed, so nothing about the real error reaches the wide event.
    """
    if node.exc is None:
        return True
    if bound_name is None:
        return False
    for expr in (node.exc, node.cause):
        if isinstance(expr, ast.Name) and expr.id == bound_name:
            return True
    return False


def _scope_contains_error_handling(
    body: list[ast.stmt], log_aliases: frozenset[str], bound_name: str | None
) -> tuple[bool, bool]:
    """``(is_empty, handled)`` for one except clause's body.

    ``bound_name`` is the handler's ``except X as <name>`` binding, needed to
    tell a re-raise that carries the original error from a fresh exception that
    silently replaces it.
    """
    real = [stmt for stmt in body if not isinstance(stmt, ast.Pass)]
    if not real:
        return True, False
    # A lone docstring/ellipsis expression is as empty as ``pass``.
    if all(isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) for stmt in real):
        return True, False
    for stmt in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(stmt, ast.Raise) and _preserves_caught_error(stmt, bound_name):
            return False, True
        if isinstance(stmt, ast.Call):
            method = _log_attr(stmt, log_aliases)
            if method in EVENT_RECORDING_METHODS or method in WIDE_EVENT_SETTERS:
                return False, True
    return False, False


def _collect_handler_facts(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    kind: str,
    methods: tuple[str, ...],
    path: str,
    paths: tuple[str, ...],
    log_aliases: frozenset[str],
) -> HandlerFacts:
    deco_line = func.decorator_list[0].lineno if func.decorator_list else func.lineno
    facts = HandlerFacts(
        name=func.name,
        line=func.lineno,
        deco_line=deco_line,
        kind=kind,
        methods=methods,
        route_path=path,
        route_paths=paths,
    )
    except_clauses: list[ast.ExceptHandler] = []
    for node in _iter_own_scope(func):
        if isinstance(node, ast.Call):
            method = _log_attr(node, log_aliases)
            if method in WIDE_EVENT_SETTERS:
                facts.sets_wide_event = True
                if method == "set_ns":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        facts.set_field_names.add(str(node.args[0].value))
                else:
                    for kw in node.keywords:
                        if kw.arg:
                            facts.set_field_names.add(kw.arg)
            elif method == "audit":
                facts.calls_audit = True
            elif method in {"info", "warning", "error", "exception", "critical", "debug"}:
                msg_is_fstring = bool(node.args) and isinstance(node.args[0], ast.JoinedStr)
                facts.log_calls.append(
                    LogCallFact(
                        line=node.lineno,
                        method=method,
                        has_kwargs=bool(node.keywords),
                        msg_is_fstring=msg_is_fstring,
                    )
                )
            elif _call_name(node) in BOUNDARY_CALLS:
                facts.has_boundary = True
        elif isinstance(node, ast.withitem):
            if isinstance(node.context_expr, ast.Call):
                if _call_name(node.context_expr) in BOUNDARY_CALLS:
                    facts.has_boundary = True
        elif isinstance(node, ast.ExceptHandler):
            except_clauses.append(node)
        elif isinstance(node, ast.Raise):
            callee = _call_name(node.exc) if node.exc else None
            has_detail = False
            if isinstance(node.exc, ast.Call):
                has_detail = any(kw.arg == "detail" for kw in node.exc.keywords)
            facts.raises.append(
                RaiseFact(
                    line=node.lineno,
                    callee=callee,
                    has_detail=has_detail,
                    is_bare=node.exc is None,
                )
            )
    for clause in except_clauses:
        is_empty, handled = _scope_contains_error_handling(clause.body, log_aliases, clause.name)
        facts.excepts.append(ExceptFact(line=clause.lineno, is_empty=is_empty, handled=handled))

    # Boundary detection recurses into nested functions (unlike the route-contract
    # facts above, which score the handler's own body). A `log_context()` inside a
    # nested helper is a real boundary; without this scan a websocket handler whose
    # boundary lives in an inline coroutine would read as having no boundary.
    if not facts.has_boundary:
        for node in _iter_nested(func):
            if isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
                if _call_name(node.context_expr) in BOUNDARY_CALLS:
                    facts.has_boundary = True
                    break
            if isinstance(node, ast.Call) and _call_name(node) in BOUNDARY_CALLS:
                facts.has_boundary = True
                break
    return facts


def _own_router_prefix(tree: ast.Module) -> str:
    """The ``APIRouter(prefix=…)`` this file declares, before it is mounted."""
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _call_name(node.value) != "APIRouter":
            continue
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return ""


def _qualified_functions(
    tree: ast.Module,
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """``(qualname, node)`` for module-level functions and their class methods."""
    out: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            out.extend(
                (f"{node.name}.{stmt.name}", stmt)
                for stmt in node.body
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return out


def collect_file_facts(
    path: Path,
    source: str,
    *,
    is_worker_module: bool,
    voice_entries: frozenset[str] = frozenset(),
    mount_prefix: str = "",
) -> FileFacts | None:
    """Parse one file into facts. Returns None when the file fails to parse.

    ``voice_entries`` are the qualified names the voice registry declared as
    LiveKit entry points in this file (see ``voice.collect_voice_registry``).
    ``mount_prefix`` is where the app includes this file's router (see
    ``routers.collect_router_mounts``); a file the app never includes has none.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    facts = FileFacts(path=path)
    facts.router_prefix = mount_prefix + _own_router_prefix(tree)
    log_aliases = _wide_event_log_aliases(tree)
    imperative_routes = _registered_routes(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            facts.imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            facts.imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Name):
            facts.names.add(node.id)
        elif isinstance(node, ast.Attribute):
            facts.names.add(node.attr)
            if node.attr in WRITE_CALLS:
                facts.has_write_calls = True

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        routes = _route_decorators(node) or imperative_routes.get(node.name, [])
        if routes:
            kind = "websocket" if any(m == "websocket" for m, _ in routes) else "api"
            methods = tuple(dict.fromkeys(m for m, _ in routes if m != "websocket"))
            route_paths = tuple(facts.router_prefix + p for _, p in routes)
            route_path = next((p for p in route_paths if p), route_paths[0])
            facts.handlers.append(
                _collect_handler_facts(node, kind, methods, route_path, route_paths, log_aliases)
            )
        elif is_worker_module and isinstance(node, ast.AsyncFunctionDef):
            if node.name.startswith("_") or node.col_offset != 0:
                continue
            task_path = f"{path.stem}:{node.name}"
            facts.handlers.append(
                _collect_handler_facts(node, "worker", (), task_path, (task_path,), log_aliases)
            )

    if voice_entries:
        for qualname, func in _qualified_functions(tree):
            if qualname not in voice_entries:
                continue
            entry_path = f"{path.stem}:{qualname}"
            facts.handlers.append(
                _collect_handler_facts(func, "voice", (), entry_path, (entry_path,), log_aliases)
            )

    return facts
