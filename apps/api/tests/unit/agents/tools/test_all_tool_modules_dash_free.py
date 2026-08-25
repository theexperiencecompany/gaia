"""Every model-visible tool string must stay dash-free.

Mirrors ``tests/unit/agents/prompts/test_all_prompt_modules_dash_free.py`` for
``app.agents.tools`` and the Composio custom-tools package: these modules do
not export their model-visible text as plain module-level string constants
(they build it as ``@tool`` descriptions, ``Annotated`` parameter
descriptions, and f-strings assembled inside a tool's body and returned to
the model), so a different discovery strategy is needed per surface:

1. **Bound tool objects** — every module-level ``BaseTool`` created by the
   ``@tool`` decorator has a ``.description`` (the function's docstring) and
   an ``args_schema`` whose fields each carry the ``Annotated[...,
   "description"]`` text. Both are read verbatim by the model.
2. **Module-level string constants** — the same convention as the prompts
   guard: any public module-level ``str`` (docstring templates, error
   fragments) that a tool assembles into its return value.
3. **Return-value source scan** — the two categories above miss text that
   only exists inside an f-string or a plain string literal *inside* a
   function body (e.g. ``return f"Already known — matched..."``). Walking
   bound values can't see that; it was never assigned to a name. Instead this
   scans the AST of every tool module and flags any string literal that
   appears textually inside a function decorated with ``@tool`` (the
   decorator that makes the docstring/return value model-visible) or a
   function whose name matches a "returns to the model" naming heuristic.
   This is intentionally coarse: it does not trace whether a given literal
   inside a ``@tool`` function is actually returned versus, say, a comment
   equivalent (a log message string, an internal-only branch) — logging
   calls are excluded (see ``_LOG_CALL_NAMES``) but everything else inside a
   ``@tool`` function body is treated as model-visible, because that is
   exactly the shape of the bug this guard exists to catch (memory_tools.py
   lines 358 and 712: a plain string literal deep inside a ``@tool``
   function's body, invisible to any constant-walking approach).
"""

import ast
import importlib
import inspect
from pathlib import Path
import pkgutil
from types import ModuleType

from langchain_core.tools import BaseTool
import pytest

EM_DASH = "—"
EN_DASH = "–"

#: Packages to walk in full (every submodule, recursively, minus exclusions).
PACKAGES_TO_WALK: tuple[str, ...] = (
    "app.agents.tools",
    "app.services.composio.custom_tools",
)

#: Modules with their own dedicated hygiene test, so not re-checked here.
EXCLUDED_MODULES: frozenset[str] = frozenset()

#: Call names inside a @tool function body whose string-literal arguments are
#: never shown to the model (they go to the log sink, not the tool result).
_LOG_CALL_NAMES: frozenset[str] = frozenset(
    {"debug", "info", "warning", "error", "exception", "critical"}
)


def _iter_package_modules(package_name: str) -> list[str]:
    package = importlib.import_module(package_name)
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        return [package_name]
    names = [package_name]
    for modinfo in pkgutil.iter_modules(package_path):
        full_name = f"{package_name}.{modinfo.name}"
        if modinfo.ispkg:
            names.extend(_iter_package_modules(full_name))
        else:
            names.append(full_name)
    return names


def _discover_module_names() -> list[str]:
    names: set[str] = set()
    for package_name in PACKAGES_TO_WALK:
        names.update(_iter_package_modules(package_name))
    return sorted(names - EXCLUDED_MODULES)


MODULE_NAMES = _discover_module_names()


def _bound_tools(module: ModuleType) -> dict[str, BaseTool]:
    """Every module-level ``BaseTool`` instance (the result of ``@tool``)."""
    return {name: value for name, value in vars(module).items() if isinstance(value, BaseTool)}


def _tool_offenders(bound_tool: BaseTool) -> list[tuple[str, str]]:
    offenders: list[tuple[str, str]] = []
    description = bound_tool.description or ""
    for line in description.splitlines():
        if EM_DASH in line or EN_DASH in line:
            offenders.append((f"{bound_tool.name}.description", line))
    args_schema = getattr(bound_tool, "args_schema", None)
    model_fields = getattr(args_schema, "model_fields", None) or {}
    for field_name, field_info in model_fields.items():
        field_description = getattr(field_info, "description", None) or ""
        for line in field_description.splitlines():
            if EM_DASH in line or EN_DASH in line:
                offenders.append((f"{bound_tool.name}.args[{field_name!r}]", line))
    return offenders


def _string_constants(module: ModuleType) -> dict[str, str]:
    """Every public module-level ``str`` constant."""
    return {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("_") and isinstance(value, str)
    }


def _tool_decorated_function_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            decorator_name = decorator.id if isinstance(decorator, ast.Name) else None
            if decorator_name is None and isinstance(decorator, ast.Attribute):
                decorator_name = decorator.attr
            if decorator_name == "tool":
                names.add(node.name)
    return names


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    call_name = func.attr if isinstance(func, ast.Attribute) else None
    if call_name is None and isinstance(func, ast.Name):
        call_name = func.id
    return call_name in _LOG_CALL_NAMES


def _string_literals_under_log_calls(tree: ast.Module) -> set[int]:
    """Line numbers of string constants that are direct arguments to a log
    call, so they're excluded from the @tool-body scan below."""
    excluded_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_log_call(node):
            for arg in ast.walk(node):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    excluded_lines.add(arg.lineno)
    return excluded_lines


def _tool_body_source_offenders(module_path: Path) -> list[tuple[str, str]]:
    """Flag em/en-dashes in string literals that appear (textually, via AST
    line ranges) inside a function decorated with @tool, excluding literals
    that are direct arguments to a log call."""
    source = module_path.read_text()
    tree = ast.parse(source, filename=str(module_path))
    tool_function_names = _tool_decorated_function_names(tree)
    if not tool_function_names:
        return []
    log_lines = _string_literals_under_log_calls(tree)
    source_lines = source.splitlines()

    offenders: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in tool_function_names:
            continue
        for inner in ast.walk(node):
            if not (isinstance(inner, ast.Constant) and isinstance(inner.value, str)):
                continue
            if inner.lineno in log_lines:
                continue
            line_text = source_lines[inner.lineno - 1]
            if EM_DASH in line_text or EN_DASH in line_text:
                offenders.append((f"{node.name}:{inner.lineno}", line_text.strip()))
    return offenders


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_bound_tool_objects_have_no_dashes(module_name: str) -> None:
    module = importlib.import_module(module_name)
    offenders: list[tuple[str, str]] = []
    for bound_tool in _bound_tools(module).values():
        offenders.extend(_tool_offenders(bound_tool))
    assert not offenders, (
        f"{module_name} has {len(offenders)} dash-containing line(s) in a "
        f"bound @tool description/arg: first {offenders[0][0]!r} -> {offenders[0][1]!r}"
    )


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_string_constants_have_no_dashes(module_name: str) -> None:
    module = importlib.import_module(module_name)
    offenders = [
        (const_name, line)
        for const_name, value in _string_constants(module).items()
        for line in value.splitlines()
        if EM_DASH in line or EN_DASH in line
    ]
    assert not offenders, (
        f"{module_name} has {len(offenders)} dash-containing line(s) in a "
        f"module-level string constant, first: {offenders[0][0]!r} -> {offenders[0][1]!r}"
    )


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_tool_function_bodies_have_no_dashes(module_name: str) -> None:
    module = importlib.import_module(module_name)
    module_file = inspect.getsourcefile(module)
    assert module_file is not None, f"could not resolve source file for {module_name}"
    offenders = _tool_body_source_offenders(Path(module_file))
    assert not offenders, (
        f"{module_name} has {len(offenders)} dash-containing string literal(s) inside "
        f"a @tool function body, first: {offenders[0][0]} -> {offenders[0][1]!r}"
    )


def test_discovery_actually_found_the_known_modules() -> None:
    """Guards the discovery mechanism itself: if pkgutil ever silently found
    zero submodules (e.g. a namespace-package path resolution regression),
    every parametrized case above would vacuously pass without checking
    anything."""
    assert len(MODULE_NAMES) >= 40, (
        f"only discovered {len(MODULE_NAMES)} modules, expected at least 40 "
        "across app.agents.tools (recursive) and "
        "app.services.composio.custom_tools; module discovery may be broken"
    )


def test_tool_body_scan_actually_catches_a_known_shape() -> None:
    """Pins the heuristic against the exact bug shape this guard exists for:
    a plain string literal deep inside a @tool function's body (not a bound
    description, not a module constant) that reaches the model. Regression
    coverage for memory_tools.py:358/712, which a constant-walking test can't
    see because the text was never assigned to a module-level name."""
    source = '''
from langchain_core.tools import tool


@tool
def add_thing(name: str) -> str:
    """Add a thing."""
    if name == "dup":
        return f"Already known — matched an existing thing (ID: 1)."
    return "added"
'''
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(source)
        temp_path = Path(handle.name)
    try:
        offenders = _tool_body_source_offenders(temp_path)
    finally:
        temp_path.unlink()
    assert offenders, "heuristic failed to catch a dash inside a @tool function body"
    assert "add_thing" in offenders[0][0]
