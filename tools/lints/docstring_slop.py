"""A docstring states the contract; it does not narrate, decorate, or repeat.

Ruff's ``D``/``DOC`` rules check a docstring's shape. This rule checks what is
inside it — the eight patterns that made 900+ docstrings in ``app/`` read like
pasted PR descriptions:

  DS1  longer than 6 lines (function) / 12 (class) / 15 (module)
  DS2  backticks — Google style is plain text; nothing here renders markup
  DS3  RST/Sphinx markup: ``x``, :param, :returns:, :raises:, .. note::, >>>
  DS4  a ``test_*`` docstring longer than one line — the test name is the doc
  DS5  a summary that only restates the function name
  DS6  an Args entry that only restates the argument name
  DS7  a type inside an Args entry — the signature already carries it
  DS8  an Examples section — prose code rots; the call sites are the examples

Docstrings that are runtime data are skipped, never rewritten: ``@tool`` /
``@custom_tool`` bodies are the model-facing tool description, ``@with_doc``
injects them, ``@router.*`` / ``@app.*`` handlers feed OpenAPI, and
``BaseModel`` / ``BaseSettings`` / ``BaseTool`` class docstrings become schema
descriptions.

No allowlist and no ``noqa`` — the cleanup that introduced this rule brought
``app/`` and ``tests/`` to zero, and a finding is fixed by shortening.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path
import re
from typing import NamedTuple

from _common import Violation

Documented = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef

RULE = "docstring-content"
WHY = (
    "a docstring that narrates, decorates or restates the signature costs every "
    "reader time and tells them nothing the code does not"
)
DOC = "tools/lints/README.md#docstring-content"

#: Runs on ``tests/`` too — DS4 lives there, and a backtick is a backtick.
INCLUDES_TESTS = True

FUNCTION_MAX_LINES = 6
CLASS_MAX_LINES = 12
MODULE_MAX_LINES = 15

#: Decorators whose docstring is consumed at runtime as a tool description;
#: bare (``@tool``) or dotted (``@composio.tools.custom_tool(...)``).
_RUNTIME_DECORATORS = frozenset({"tool", "custom_tool", "with_doc"})
#: Route registrations feed OpenAPI. Only the dotted form (``@router.patch``)
#: counts — a bare ``@patch`` is ``unittest.mock.patch``.
_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "api_route", "websocket"})
#: Base classes whose class docstring becomes a schema description. Subclasses
#: of these defined anywhere in the app (CamelModel, MongoDocument, …) count too.
_RUNTIME_BASES = frozenset({"BaseModel", "BaseSettings", "BaseTool", "BaseToolkit"})
_APP_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api" / "app"

_RST = re.compile(r"``|:param\b|:returns?:|:raises?:|:type\b|:rtype:|\.\. \w+::|^\s*>>>", re.M)
_EXAMPLES = re.compile(r"^\s*Examples?\s*:\s*$", re.M)
_ARGS_SECTION = re.compile(r"^\s*(?:Args|Arguments)\s*:\s*\n((?:[ \t]+\S.*\n?)+)", re.M)
_ARGS_ENTRY = re.compile(r"\s*(\*{0,2}\w+)\s*(\([^)]*\))?\s*:\s*(.*)")

#: Words that carry no information on their own; a description made only of
#: these plus the name's own tokens is a restatement.
_FILLER = frozenset(
    (
        "the",
        "a",
        "an",
        "of",
        "to",
        "for",
        "and",
        "or",
        "in",
        "on",
        "is",
        "this",
        "that",
        "with",
        "from",
        "if",
        "by",
        "its",
        "it",
        "given",
        "value",
        "values",
        "object",
        "instance",
        "string",
        "list",
        "dict",
        "id",
        "name",
        "return",
        "returns",
        "get",
        "gets",
        "set",
        "sets",
        "check",
        "checks",
        "whether",
        "current",
        "specified",
        "provided",
        "new",
        "all",
        "data",
        "info",
        "information",
    )
)


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in _FILLER}


def _base_ref(node: ast.expr) -> str:
    """Return a base class as written, dotted (``memory_models.MemoryDocument``), or empty."""
    if isinstance(node, ast.Call | ast.Subscript):
        node = node.func if isinstance(node, ast.Call) else node.value
    if isinstance(node, ast.Attribute):
        qualifier = _base_ref(node.value)
        return f"{qualifier}.{node.attr}" if qualifier else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_runtime_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr in _RUNTIME_DECORATORS or target.attr in _ROUTE_METHODS
    return isinstance(target, ast.Name) and target.id in _RUNTIME_DECORATORS


class _Module(NamedTuple):
    classes: dict[str, list[str]]
    #: ``from x import y [as z]`` -> {z or y: (x, y)}; y may be a class or a submodule.
    imports: dict[str, tuple[str, str]]
    #: ``import a.b [as c]`` -> {c: "a.b"}, or {"a": "a"} without an alias.
    module_aliases: dict[str, str]


#: Answers "is this base, as written in this module, a runtime base?".
RuntimeBase = Callable[[str, str], bool]


def _module_name(path: Path) -> str:
    parts = path.with_suffix("").parts
    start = len(parts) - 1 - parts[::-1].index("app") if "app" in parts else len(parts) - 1
    return ".".join(parts[start:])


def _scan(path: Path) -> _Module:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = {
        node.name: [_base_ref(base) for base in node.bases]
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    imports = {
        alias.asname or alias.name: (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    module_aliases = {
        alias.asname or alias.name.partition(".")[0]: alias.name
        if alias.asname
        else alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    return _Module(classes, imports, module_aliases)


@cache
def _app_modules() -> dict[str, _Module]:
    """Return every app module's classes and imports, so a single-file run sees indirect bases."""
    paths = sorted(_APP_ROOT.rglob("*.py")) if _APP_ROOT.is_dir() else []
    return {_module_name(path): _scan(path) for path in paths}


def _runtime_base_resolver(files: list[Path]) -> RuntimeBase:
    """Resolve each base through its own module's classes and imports, then walk its chain.

    A bare name falls back to the one repo class of that name, and to nothing when two share it.
    """
    modules = {**_app_modules(), **{_module_name(path): _scan(path) for path in files}}
    owners: dict[str, list[str]] = {}
    for module, scanned in modules.items():
        for name in scanned.classes:
            owners.setdefault(name, []).append(module)
    memo: dict[tuple[str, str], bool] = {}

    def module_path(module: str, qualifier: str) -> str | None:
        scanned = modules.get(module)
        head, _, rest = qualifier.partition(".")
        if scanned is None:
            return None
        if head in scanned.module_aliases:
            base = scanned.module_aliases[head]
        elif head in scanned.imports:
            base = ".".join(scanned.imports[head])
        else:
            return None
        return f"{base}.{rest}" if rest else base

    def resolve(module: str, ref: str) -> tuple[str, str] | None:
        qualifier, _, name = ref.rpartition(".")
        if qualifier:
            target_module = module_path(module, qualifier)
            source = modules.get(target_module) if target_module else None
            return (target_module, name) if source and name in source.classes else None
        scanned = modules.get(module)
        if scanned and name in scanned.classes:
            return module, name
        if scanned and name in scanned.imports:
            source_module, source_name = scanned.imports[name]
            source = modules.get(source_module)
            return (
                (source_module, source_name) if source and source_name in source.classes else None
            )
        defined_in = owners.get(name, [])
        return (defined_in[0], name) if len(defined_in) == 1 else None

    def is_runtime_base(
        module: str, ref: str, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> bool:
        target = resolve(module, ref)
        if target is None:
            scanned = modules.get(module)
            name = ref.rpartition(".")[2]
            if "." not in ref and scanned and name in scanned.imports:
                name = scanned.imports[name][1]
            return name in _RUNTIME_BASES
        if target in memo:
            return memo[target]
        if target in seen:
            return False
        target_module, target_name = target
        reached = any(
            is_runtime_base(target_module, base, seen | {target})
            for base in modules[target_module].classes[target_name]
        )
        memo[target] = reached
        return reached

    return is_runtime_base


def _is_runtime_docstring(node: Documented, module: str, runtime_base: RuntimeBase) -> bool:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return any(_is_runtime_decorator(d) for d in node.decorator_list)
    if isinstance(node, ast.ClassDef):
        return any(runtime_base(module, _base_ref(b)) for b in node.bases)
    return False


def _args_entries(doc: str) -> Iterator[tuple[str, str | None, str]]:
    section = _ARGS_SECTION.search(doc + "\n")
    if not section:
        return
    for line in section.group(1).splitlines():
        entry = _ARGS_ENTRY.match(line)
        if entry:
            yield entry.group(1).lstrip("*"), entry.group(2), entry.group(3)


Finding = tuple[str, str, str]


def _shape_findings(doc: str, node: Documented, name: str, is_test_file: bool) -> list[Finding]:
    n_lines = doc.count("\n") + 1
    if isinstance(node, ast.Module):
        cap = MODULE_MAX_LINES
    elif isinstance(node, ast.ClassDef):
        cap = CLASS_MAX_LINES
    else:
        cap = FUNCTION_MAX_LINES
    is_test_function = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and name.startswith(
        "test_"
    )
    checks: list[tuple[bool, Finding]] = [
        (
            n_lines > cap,
            (
                "DS1",
                f"docstring of `{name}` is {n_lines} lines (max {cap})",
                "keep the summary and the one non-obvious constraint; the why belongs in the PR",
            ),
        ),
        (
            "`" in doc,
            (
                "DS2",
                f"backticks in the docstring of `{name}`",
                "plain text — nothing renders markup here",
            ),
        ),
        (
            bool(_RST.search(doc)),
            ("DS3", f"RST/Sphinx markup in the docstring of `{name}`", "Google style, plain text"),
        ),
        (
            is_test_file and is_test_function and n_lines > 1,
            (
                "DS4",
                f"test docstring of `{name}` is {n_lines} lines",
                "one line or none — the test name is the doc",
            ),
        ),
        (
            bool(_EXAMPLES.search(doc)),
            (
                "DS8",
                f"Examples section in the docstring of `{name}`",
                "delete it — the call sites are the examples",
            ),
        ),
    ]
    return [finding for failed, finding in checks if failed]


def _restatement_findings(doc: str, name: str) -> list[Finding]:
    findings: list[Finding] = []
    summary_words = _words(doc.split("\n", 1)[0])
    if summary_words and summary_words <= _words(name):
        findings.append(
            (
                "DS5",
                f"summary of `{name}` only restates its name",
                "delete it, or say what the name does not",
            )
        )
    for arg, typ, desc in _args_entries(doc):
        desc_words = _words(desc)
        if desc_words and desc_words <= _words(arg):
            findings.append(
                ("DS6", f"Args entry `{arg}` in `{name}` only restates its name", "drop the entry")
            )
        if typ:
            findings.append(
                (
                    "DS7",
                    f"type written in Args entry `{arg}` of `{name}`",
                    "the signature carries the type",
                )
            )
    return findings


def _check_node(
    path: Path, node: Documented, is_test_file: bool, runtime_base: RuntimeBase
) -> list[Violation]:
    doc = ast.get_docstring(node, clean=True)
    if not doc or _is_runtime_docstring(node, _module_name(path), runtime_base):
        return []
    line = 1 if isinstance(node, ast.Module) else node.body[0].lineno
    name = getattr(node, "name", path.stem)
    findings = [*_shape_findings(doc, node, name, is_test_file), *_restatement_findings(doc, name)]
    return [
        Violation(path=path, line=line, detail=f"{code}: {detail}", fix=fix)
        for code, detail, fix in findings
    ]


def check(files: list[Path]) -> list[Violation]:
    """Return docstring-content violations across ``files``."""
    runtime_base = _runtime_base_resolver(files)
    violations: list[Violation] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        is_test_file = "tests" in path.parts or path.name.startswith("test_")
        for node in ast.walk(tree):
            if isinstance(node, Documented):
                violations.extend(_check_node(path, node, is_test_file, runtime_base))
    return violations
