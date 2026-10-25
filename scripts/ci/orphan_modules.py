#!/usr/bin/env python3
"""Report app modules that no production module imports.

Vulture is name-based: an unused module whose entry point happens to share a
name with an unrelated local (`timer` in email_processor.py) reads as used, and
its enforced set deliberately skips module-level variables. Tests are excluded
from vulture, so a module imported only by tests is invisible there.

This walks the real import graph from the process entrypoints and reports any
module nothing outside tests reaches. Dynamic entrypoints (a module named only
in a CLI flag) are declared in DYNAMIC_MODULES with the reason.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "api" / "app"

# Imported as a uvicorn target (infra/docker/docker-compose.yml), never by an
# `import` statement.
STATIC_ENTRYPOINTS = {
    "app.main",
    "app.worker",
    "app.services.embedding_sidecar.server",
}

# Imported only by path from a command line, never by an `import` statement.
DYNAMIC_MODULES = {
    "app.workers.config.log_config": (
        "arq --custom-log-dict app.workers.config.log_config.ARQ_LOG_CONFIG"
    ),
}


def _module_name(path: Path, root: Path) -> tuple[str, bool]:
    """Return (dotted module name, is_package) for a file under root."""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(["app", *parts]), is_package


def _imports(tree: ast.AST, module: str, is_package: bool) -> set[str]:
    """Every dotted app path this module mentions in an import or a string literal."""
    found: set[str] = set()
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                prefix = ".".join(package_parts[: len(package_parts) - (node.level - 1)])
                base = f"{prefix}.{base}" if base else prefix
            else:
                targets = [base] if base.startswith("app.") else []
            if base.startswith("app."):
                targets = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("app."):
                targets = [node.value]
        found.update(target for target in targets if target.startswith("app."))
    return found


def orphan_modules(app_dir: Path = APP_DIR) -> list[tuple[Path, str]]:
    """Return (file, module) pairs no production import path reaches."""
    modules: dict[str, Path] = {}
    packages: dict[str, bool] = {}
    for path in sorted(app_dir.rglob("*.py")):
        module, is_package = _module_name(path, app_dir)
        modules[module] = path
        packages[module] = is_package

    edges: dict[str, set[str]] = defaultdict(set)
    roots: set[str] = set()
    for module, path in modules.items():
        source = path.read_text()
        if '__name__ == "__main__"' in source or module.startswith("app.scripts."):
            roots.add(module)
        for target in _imports(ast.parse(source), module, packages[module]):
            if target in modules:
                edges[module].add(target)

    roots.update(module for module in STATIC_ENTRYPOINTS if module in modules)
    roots.update(module for module in DYNAMIC_MODULES if module in modules)

    reached: set[str] = set()
    pending = list(roots)
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.extend(edges[module])
        parent = module.rsplit(".", 1)[0] if "." in module else ""
        while parent.startswith("app") and parent not in reached:
            pending.append(parent)
            parent = parent.rsplit(".", 1)[0] if "." in parent else ""

    return [
        (path, module)
        for module, path in sorted(modules.items())
        if module not in reached and not packages[module]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=APP_DIR)
    args = parser.parse_args(argv)

    orphans = orphan_modules(args.app_dir)
    for path, module in orphans:
        try:
            shown = path.relative_to(Path.cwd())
        except ValueError:
            shown = path
        print(f"{shown}:1: module {module} is imported by no production module")
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
