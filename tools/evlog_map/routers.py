"""Router mount registry — the prefix each endpoint module is actually served under.

FastAPI builds a served path from three parts: every ``include_router(prefix=…)``
on the way down from the app, the module's own ``APIRouter(prefix=…)``, and the
decorator's path. A single-file AST pass sees only the last two, so
``endpoints/memory.py`` reads as ``""`` instead of ``/api/v1/memory`` and *every*
route loses the ``/api/v1`` mount — which makes path-based classification
(sensitivity, infra exemption) judge paths the server never serves.

Like the worker and voice registries, the wiring is parsed, never hardcoded:
``app_factory.py``'s ``app.include_router(...)`` calls are the roots, and each
target module is followed down its own ``include_router(...)`` chain (two levels
deep under ``endpoints/integrations``). Anything that cannot be resolved raises
— a silently dropped branch would hand ~90 handlers a wrong path and nothing
would say so. A module nobody includes simply has no mount prefix:
``embedding_sidecar/server.py`` is its own ASGI app, not a branch of this one.
"""

from __future__ import annotations

import ast
from pathlib import Path

from facts import repo_relative

_INCLUDE_ROUTER = "include_router"
_PREFIX_KWARG = "prefix"


def _module_file(module: str, package_root: Path) -> Path | None:
    """The file backing a dotted module name, module or package."""
    relative = module.replace(".", "/")
    for candidate in (package_root / f"{relative}.py", package_root / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _import_bindings(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Local name → ``(package, imported name)`` for every ``from X import Y`` binding.

    Covers both shapes the wiring uses: ``from …endpoints import voice`` (the
    name is a module) and ``from …v1.routes import router as api_router`` (the
    name is a router object inside a module).
    """
    bindings: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module or node.level:
            continue
        for alias in node.names:
            bindings[alias.asname or alias.name] = (node.module, alias.name)
    return bindings


def _router_module(
    expr: ast.expr, bindings: dict[str, tuple[str, str]], package_root: Path, source: Path
) -> str:
    """The module owning the router named by an ``include_router`` argument."""
    base = expr.value if isinstance(expr, ast.Attribute) else expr
    if not isinstance(base, ast.Name) or base.id not in bindings:
        raise ValueError(
            f"{source}: include_router() argument {ast.unparse(expr)!r} does not "
            "resolve to an imported router — the wiring moved, paths would be wrong"
        )
    package, name = bindings[base.id]
    if _module_file(f"{package}.{name}", package_root) is not None:
        return f"{package}.{name}"
    return package


def _include_prefix(call: ast.Call, source: Path) -> str:
    for keyword in call.keywords:
        if keyword.arg != _PREFIX_KWARG:
            continue
        if not (isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)):
            raise ValueError(
                f"{source}:{call.lineno}: include_router(prefix=…) is not a string "
                "literal — the served path cannot be resolved statically"
            )
        return keyword.value.value
    return ""


def _include_router_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == _INCLUDE_ROUTER
        and node.args
    ]


def _mount(
    module: str,
    prefix: str,
    package_root: Path,
    mounts: dict[str, str],
    visited: set[str],
) -> None:
    """Record ``module``'s mount prefix, then follow the routers it includes."""
    file = _module_file(module, package_root)
    if file is None:
        raise ValueError(f"included router module {module!r} has no file under {package_root}")
    key = repo_relative(file.resolve())
    mounted_at = mounts.get(key)
    if mounted_at is not None and mounted_at != prefix:
        raise ValueError(
            f"{key} is included at both {mounted_at!r} and {prefix!r} — its handlers "
            "serve two paths, which one entry point cannot represent"
        )
    mounts[key] = prefix
    if module in visited:
        return
    visited.add(module)

    tree = ast.parse(file.read_text(encoding="utf-8"))
    bindings = _import_bindings(tree)
    for call in _include_router_calls(tree):
        child = _router_module(call.args[0], bindings, package_root, file)
        _mount(child, prefix + _include_prefix(call, file), package_root, mounts, visited)


def collect_router_mounts(app_factory: Path, package_root: Path) -> dict[str, str]:
    """Repo-relative module path → the prefix its router is mounted at, app-wide.

    Keyed the way ``repo_relative`` keys everything else, so a file scanned out
    of the CI merge-base worktree resolves to the same mount as its in-repo
    counterpart — otherwise the base half of the per-file ratchet would score
    every route unprefixed and read HEAD's real paths as a regression.
    """
    tree = ast.parse(app_factory.read_text(encoding="utf-8"))
    bindings = _import_bindings(tree)
    calls = _include_router_calls(tree)
    if not calls:
        raise ValueError(
            f"no {_INCLUDE_ROUTER}() wiring found in {app_factory} — app factory moved?"
        )

    mounts: dict[str, str] = {}
    visited: set[str] = set()
    for call in calls:
        module = _router_module(call.args[0], bindings, package_root, app_factory)
        _mount(module, _include_prefix(call, app_factory), package_root, mounts, visited)
    return mounts
