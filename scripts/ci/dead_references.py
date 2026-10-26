#!/usr/bin/env python3
"""Report app symbols no production code references.

Name matching is not evidence of use: a `timer` local in another file made a
dead decorator module look live, and a common `create_session` hid dead
functions. This resolves imports and attribute chains to the symbol they
actually name, then counts references from production modules only.

Two verdicts are reported:

* DEAD       nothing outside the definition references it
* TEST-ONLY  only tests reference it — product code kept alive by its tests

Dynamic entrypoints (a module named only in a CLI flag, a symbol resolved via
getattr) are declared in DYNAMIC_SYMBOLS with the reason, never guessed.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "apps" / "api" / "app"

# Production code that may reference an app symbol. Tests are counted
# separately: a test reference does not keep product code alive.
PRODUCTION_ROOTS = (
    "apps/api/app",
    "apps/api/scripts",
    "apps/voice-agent",
    "apps/bots",
    "libs",
    "scripts",
    "tools",
)
TEST_ROOTS = ("apps/api/tests",)

# Decorators that register the decorated object for dynamic dispatch. The
# function is live even though nothing imports it by name.
REGISTERING_DECORATORS = {
    "action",
    "custom_tool",
    "delete",
    "exception_handler",
    "field_serializer",
    "field_validator",
    "get",
    "middleware",
    "model_serializer",
    "model_validator",
    "on",
    "patch",
    "post",
    "put",
    "register_after_hook",
    "register_before_hook",
    "register_schema_modifier",
    "register_suite",
    "websocket",
}

# (module, symbol) pairs reached by name from outside the import graph.
DYNAMIC_SYMBOLS: dict[tuple[str, str], str] = {
    ("app.workers.config.log_config", "ARQ_LOG_CONFIG"): (
        "arq --custom-log-dict app.workers.config.log_config.ARQ_LOG_CONFIG"
    ),
    ("app.main", "app"): "uvicorn target app.main:app (infra/docker/docker-compose.yml)",
}

SKIP_PARTS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".nx",
    ".git",
    ".claude",
    ".agents",
    "mutants",
    "verify-logs",
}


@dataclass(frozen=True)
class Definition:
    module: str
    name: str
    path: Path
    line: int
    kind: str


def _python_files(root: Path) -> list[Path]:
    if (root / ".git").exists():
        out = subprocess.check_output(
            ["git", "ls-files", "*.py"], cwd=root, text=True, stderr=subprocess.DEVNULL
        )
        return [root / line for line in out.splitlines() if line and (root / line).exists()]
    return [
        path
        for path in root.rglob("*.py")
        if not SKIP_PARTS.intersection(path.parts) and path.name != "conftest.py"
    ]


def _module_name(path: Path, root: Path) -> tuple[str, bool]:
    """Return the importable name (app.* for app modules, repo-relative otherwise)."""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    if parts[:3] == ["apps", "api", "app"]:
        parts = ["app", *parts[3:]]
    return ".".join(parts), is_package


class Scope:
    """Import aliases in one module, resolved to module or module.symbol."""

    def __init__(self, module: str, is_package: bool, tree: ast.AST) -> None:
        self.module = module
        self.is_package = is_package
        self.aliases: dict[str, tuple[str, str | None]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith("app"):
                        continue
                    if alias.asname:
                        self.aliases[alias.asname] = (alias.name, None)
                    else:
                        root = alias.name.split(".")[0]
                        self.aliases[root] = (root, None)
            elif isinstance(node, ast.ImportFrom):
                base = self._absolute_base(node)
                if not base.startswith("app"):
                    continue
                for alias in node.names:
                    target = f"{base}.{alias.name}"
                    self.aliases[alias.asname or alias.name] = (target, None)

    def _absolute_base(self, node: ast.ImportFrom) -> str:
        base = node.module or ""
        if not node.level:
            return base
        parts = self.module.split(".") if self.is_package else self.module.split(".")[:-1]
        prefix = ".".join(parts[: len(parts) - (node.level - 1)])
        return f"{prefix}.{base}" if base else prefix

    def resolve_chain(self, node: ast.AST, modules: set[str]) -> tuple[str, str] | None:
        """Resolve a Name/Attribute chain to (module, symbol), if it names one."""
        parts: list[str] = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if not isinstance(cursor, ast.Name):
            return None
        parts.append(cursor.id)
        parts.reverse()

        head, *rest = parts
        if head in self.aliases:
            base, _ = self.aliases[head]
            path = base.split(".") + rest
        else:
            path = [self.module, *parts]

        # Longest module prefix; the remainder is the symbol path.
        for cut in range(len(path), 0, -1):
            candidate = ".".join(path[:cut])
            if candidate in modules:
                remainder = path[cut:]
                if len(remainder) == 1:
                    return candidate, remainder[0]
                if not remainder:
                    return candidate, "__module__"
                return None
        return None


def _python_paths(root: Path) -> list[Path]:
    return _python_files(root)


def _roots(root: Path) -> tuple[list[Path], list[Path]]:
    production: list[Path] = []
    tests: list[Path] = []
    for path in _python_paths(root):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(TEST_ROOTS):
            tests.append(path)
        elif rel.startswith(PRODUCTION_ROOTS):
            production.append(path)
    return production, tests


def _definitions(app_dir: Path, root: Path) -> list[Definition]:
    defs: list[Definition] = []
    for path in sorted(app_dir.rglob("*.py")):
        module, _ = _module_name(path, root / "apps/api")
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _registered(node):
                    continue
                defs.append(Definition(module, node.name, path, node.lineno, "function"))
            elif isinstance(node, ast.ClassDef):
                if _registered(node):
                    continue
                defs.append(Definition(module, node.name, path, node.lineno, "class"))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id != "__all__":
                        defs.append(Definition(module, target.id, path, node.lineno, "name"))
    return defs


def _registered(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in REGISTERING_DECORATORS:
            return True
        if isinstance(target, ast.Name) and target.id in REGISTERING_DECORATORS:
            return True
    return False


def _record_name(
    node: ast.Name,
    module: str,
    scope: Scope,
    store: set[tuple[str, str]],
    imported_modules: set[str],
) -> None:
    store.add((module, node.id))
    imported = scope.aliases.get(node.id)
    if not imported:
        return
    target, _ = imported
    imported_modules.add(target)
    if target.rsplit(".", 1)[-1][:1].isupper():
        parent, symbol = target.rsplit(".", 1)
        store.add((parent, symbol))


def _record_import(node: ast.Import, imported_modules: set[str]) -> None:
    imported_modules.update(alias.name for alias in node.names if alias.name.startswith("app"))


def _record_import_from(
    node: ast.ImportFrom, scope: Scope, store: set[tuple[str, str]], imported_modules: set[str]
) -> None:
    base = scope._absolute_base(node)
    if not base.startswith("app"):
        return
    imported_modules.add(base)
    for imported in node.names:
        store.add((base, "*" if imported.name == "*" else imported.name))


def _record_node(
    node: ast.AST,
    module: str,
    scope: Scope,
    module_names: set[str],
    store: set[tuple[str, str]],
    imported_modules: set[str],
) -> None:
    """Record the app symbols one AST node refers to."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        _record_name(node, module, scope, store, imported_modules)
    elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        resolved = scope.resolve_chain(node, module_names)
        if resolved:
            store.add(resolved)
            imported_modules.add(resolved[0])
    elif isinstance(node, ast.Import):
        _record_import(node, imported_modules)
    elif isinstance(node, ast.ImportFrom):
        _record_import_from(node, scope, store, imported_modules)
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        _record_string(node.value, module_names, store, imported_modules)


def _record_string(
    value: str,
    module_names: set[str],
    store: set[tuple[str, str]],
    imported_modules: set[str],
) -> None:
    """Record module/symbol paths mentioned in a string (uvicorn targets, importlib)."""
    if value in module_names:
        imported_modules.add(value)
    elif not value.startswith("app."):
        return
    elif ":" in value:
        mod, _, sym = value.partition(":")
        if mod in module_names and sym:
            store.add((mod, sym))
    else:
        mod, _, sym = value.rpartition(".")
        if mod in module_names and sym:
            store.add((mod, sym))


def _collect_file(
    path: Path,
    root: Path,
    module_names: set[str],
    store: set[tuple[str, str]],
    imported_modules: set[str],
) -> None:
    """Collect this file's references into one bucket."""
    module, is_package = _module_name(path, root)
    tree = ast.parse(path.read_text())
    scope = Scope(module, is_package, tree)
    for node in ast.walk(tree):
        _record_node(node, module, scope, module_names, store, imported_modules)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    store.add((module, item.value))


def _references(
    files: tuple[list[Path], list[Path]],
    root: Path,
    modules: dict[str, Path],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]], set[str]]:
    """Return (production refs, test refs, production modules imported)."""
    production: set[tuple[str, str]] = set()
    tests: set[tuple[str, str]] = set()
    imported_modules: set[str] = set()
    module_names = set(modules)

    for paths, store in zip(files, (production, tests)):
        for path in paths:
            _collect_file(path, root, module_names, store, imported_modules)

    for store in (production, tests):
        for module, symbol in list(store):
            if symbol == "*":
                for name in _module_definitions(modules[module]):
                    store.add((module, name))
    return production, tests, imported_modules


def _module_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def audit(app_dir: Path = APP_DIR, root: Path = REPO_ROOT) -> list[tuple[Definition, str]]:
    """Return (definition, verdict) for every app symbol not referenced in production."""
    production_files, test_files = _roots(root)
    all_files = _python_paths(root)
    modules = {_module_name(path, root)[0]: path for path in all_files}

    production, tests, imported_modules = _references((production_files, test_files), root, modules)
    findings: list[tuple[Definition, str]] = []
    for definition in _definitions(app_dir, root):
        if (definition.module, definition.name) in DYNAMIC_SYMBOLS:
            continue
        if definition.name.startswith("__"):
            continue
        if (definition.module, definition.name) in production:
            continue
        verdict = "TEST-ONLY" if (definition.module, definition.name) in tests else "DEAD"
        findings.append((definition, verdict))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=APP_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--show-test-only", action="store_true")
    args = parser.parse_args(argv)

    findings = audit(args.app_dir, args.repo_root)
    shown = [f for f in findings if args.show_test_only or f[1] == "DEAD"]
    for definition, verdict in shown:
        try:
            path = definition.path.relative_to(args.repo_root)
        except ValueError:
            path = definition.path
        print(f"{path}:{definition.line}: {verdict} {definition.module}.{definition.name}")
    return 1 if shown else 0


if __name__ == "__main__":
    raise SystemExit(main())
