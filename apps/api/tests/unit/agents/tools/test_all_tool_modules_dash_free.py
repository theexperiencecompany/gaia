"""Every model-visible tool string must stay dash-free.

Mirrors test_all_prompt_modules_dash_free.py for app.agents.tools and the
Composio custom-tools package, using three discovery strategies since these
modules don't export model-visible text as plain module-level constants:

1. Bound tool objects — a @tool-decorated BaseTool's .description and its
   args_schema's Annotated[..., "description"] fields.
2. Module-level string constants assembled into a tool's return value.
3. An AST scan of string literals appearing textually inside a @tool function
   body (an f-string return value isn't bound to any name, so 1 and 2 miss
   it), excluding logging calls (_LOG_CALL_NAMES). Regression coverage for
   memory_tools.py:358/712, a literal invisible to constant-walking.
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
    """Every module-level BaseTool instance (the result of @tool)."""
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
    """Every public module-level str constant."""
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
    """Line numbers of string constants passed directly to a log call, excluded from the @tool-body scan below."""
    excluded_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_log_call(node):
            for arg in ast.walk(node):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    excluded_lines.add(arg.lineno)
    return excluded_lines


def _tool_body_source_offenders(module_path: Path) -> list[tuple[str, str]]:
    """Flag em/en-dashes in string literals inside a @tool-decorated function, excluding log-call arguments."""
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
    """If pkgutil ever silently found zero submodules, every parametrized case above would vacuously pass."""
    assert len(MODULE_NAMES) >= 40, (
        f"only discovered {len(MODULE_NAMES)} modules, expected at least 40 "
        "across app.agents.tools (recursive) and "
        "app.services.composio.custom_tools; module discovery may be broken"
    )


def test_tool_body_scan_actually_catches_a_known_shape() -> None:
    """Regression coverage for memory_tools.py:358/712, a literal never assigned to a name that constant-walking misses."""
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
