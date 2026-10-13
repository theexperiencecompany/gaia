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

Docstrings that are runtime data are skipped, never rewritten. Two sources,
never duplicated against each other:

- The ONE source of truth for "this whole file's docstrings are runtime
  data, not prose" is root pyproject.toml's own
  ``[tool.ruff.lint.per-file-ignores]`` -- whichever globs already carry
  ``"D"`` (route handlers feeding OpenAPI, ``@tool`` bodies, pydantic
  models/schemas, argparse ``--help`` scripts, …). A file matched by one of
  those globs is skipped entirely here too, so the two never drift.
- What ruff's per-file config cannot see, because it is not file-shaped:
  ``@tool`` / ``@custom_tool`` / ``@with_doc``-decorated functions,
  ``@router.*`` handlers, ``BaseModel``/``BaseSettings``/``BaseTool``
  subclasses anywhere, and a ``BaseModel``/``TypedDict`` whose name is
  passed to ``with_structured_output``/``bind_tools`` anywhere in the tree
  (a literal class name only -- a schema threaded through a variable or a
  wrapper function is invisible to this).

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

from _common import Violation, find_repo_root, ruff_exempt_files

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
#: Calls whose argument is a structured-output/tool schema, not app logic.
_STRUCTURED_OUTPUT_CALLS = frozenset({"with_structured_output", "bind_tools"})
#: Base classes a structured-output schema is allowed to be.
_STRUCTURED_OUTPUT_BASES = frozenset({"BaseModel", "TypedDict"})
#: Used only when no pyproject.toml is found above the scanned files (e.g. an
#: isolated tmp_path test tree) -- this file's own repo, not a hardcoded fact
#: about whichever tree is actually being scanned.
_DEFAULT_APP_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api" / "app"
#: Set by run.py's ``--repo-root`` when auto-detection (walking up from the
#: scanned files to a pyproject.toml) can't find the right tree.
_REPO_ROOT_OVERRIDE: Path | None = None


def set_repo_root(path: Path | None) -> None:
    """Override repo-root auto-detection, for scanning a tree other than this file's own."""
    global _REPO_ROOT_OVERRIDE
    _REPO_ROOT_OVERRIDE = path


def _repo_root_for(files: list[Path]) -> Path | None:
    return _REPO_ROOT_OVERRIDE or find_repo_root(files)


def _app_root_for(files: list[Path]) -> Path:
    repo_root = _repo_root_for(files)
    return (repo_root / "apps" / "api" / "app") if repo_root else _DEFAULT_APP_ROOT


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


#: Answers "is this base, as written in this module, one of these target bases?".
RuntimeBase = Callable[[str, str, frozenset[str]], bool]


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
def _app_modules(app_root: Path) -> dict[str, _Module]:
    """Return every app module's classes and imports, so a single-file run sees indirect bases."""
    paths = sorted(app_root.rglob("*.py")) if app_root.is_dir() else []
    return {_module_name(path): _scan(path) for path in paths}


def _runtime_base_resolver(files: list[Path], app_root: Path) -> RuntimeBase:
    """Resolve each base through its own module's classes and imports, then walk its chain.

    A bare name falls back to the one repo class of that name, and to nothing when two share it.
    Built once per run and queried against different target-base sets (see ``RuntimeBase``), so
    the (often large) ``files`` scan happens only once regardless of how many sets are checked.
    """
    modules = {**_app_modules(app_root), **{_module_name(path): _scan(path) for path in files}}
    owners: dict[str, list[str]] = {}
    for module, scanned in modules.items():
        for name in scanned.classes:
            owners.setdefault(name, []).append(module)
    memo: dict[tuple[frozenset[str], str, str], bool] = {}

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
        module: str,
        ref: str,
        target_bases: frozenset[str],
        seen: frozenset[tuple[str, str]] = frozenset(),
    ) -> bool:
        target = resolve(module, ref)
        if target is None:
            scanned = modules.get(module)
            name = ref.rpartition(".")[2]
            if "." not in ref and scanned and name in scanned.imports:
                name = scanned.imports[name][1]
            return name in target_bases
        key = (target_bases, *target)
        if key in memo:
            return memo[key]
        if target in seen:
            return False
        target_module, target_name = target
        reached = any(
            is_runtime_base(target_module, base, target_bases, seen | {target})
            for base in modules[target_module].classes[target_name]
        )
        memo[key] = reached
        return reached

    return is_runtime_base


class _ModuleSignals(NamedTuple):
    """The two runtime-consumption facts this rule needs from one pass over a tree."""

    reads_own_doc: bool
    #: Bare class names written as an argument to with_structured_output/bind_tools.
    structured_output_refs: frozenset[str]


def _module_signals(tree: ast.AST) -> _ModuleSignals:
    """Scan a tree once for ``__doc__`` reads and structured-output/bind_tools schema references.

    A literal ``ast.Name`` argument only — a schema threaded through a
    variable or a wrapper function (this repo's own ``ainvoke_structured``
    included) is invisible to this, same limit as the base-class resolver.
    """
    reads_own_doc = False
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__doc__" and isinstance(node.ctx, ast.Load):
            reads_own_doc = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _STRUCTURED_OUTPUT_CALLS:
                for arg in (*node.args, *(kw.value for kw in node.keywords)):
                    if isinstance(arg, ast.Name):
                        refs.add(arg.id)
    return _ModuleSignals(reads_own_doc, frozenset(refs))


@cache
def _app_structured_output_names(app_root: Path) -> frozenset[str]:
    """Return every class name passed to with_structured_output/bind_tools anywhere in the app."""
    paths = sorted(app_root.rglob("*.py")) if app_root.is_dir() else []
    names: set[str] = set()
    for path in paths:
        names.update(
            _module_signals(ast.parse(path.read_text(encoding="utf-8"))).structured_output_refs
        )
    return frozenset(names)


def _is_runtime_docstring(
    node: Documented,
    module: str,
    runtime_base: RuntimeBase,
    structured_names: frozenset[str],
    reads_own_doc: bool,
) -> bool:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return any(_is_runtime_decorator(d) for d in node.decorator_list)
    if isinstance(node, ast.ClassDef):
        if any(runtime_base(module, _base_ref(b), _RUNTIME_BASES) for b in node.bases):
            return True
        return node.name in structured_names and any(
            runtime_base(module, _base_ref(b), _STRUCTURED_OUTPUT_BASES) for b in node.bases
        )
    return reads_own_doc


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


class _TreeContext(NamedTuple):
    """Resolvers shared across every file in one ``check()`` invocation."""

    runtime_base: RuntimeBase
    structured_names: frozenset[str]


def _check_node(
    path: Path, node: Documented, is_test_file: bool, ctx: _TreeContext, reads_own_doc: bool
) -> list[Violation]:
    doc = ast.get_docstring(node, clean=True)
    module = _module_name(path)
    if not doc or _is_runtime_docstring(
        node, module, ctx.runtime_base, ctx.structured_names, reads_own_doc
    ):
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
    repo_root = _repo_root_for(files)
    app_root = _app_root_for(files)
    pyproject_exempt = ruff_exempt_files(files, "D", repo_root)
    # Each file is parsed and walked for its runtime signals once, then reused
    # for the node walk below — the base resolver still re-scans ``files``
    # itself (it also needs each class's bases/imports, not just its tree).
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path)) for path in files
    }
    signals = {path: _module_signals(tree) for path, tree in trees.items()}
    ctx = _TreeContext(
        runtime_base=_runtime_base_resolver(files, app_root),
        structured_names=_app_structured_output_names(app_root)
        | frozenset().union(*(s.structured_output_refs for s in signals.values())),
    )
    violations: list[Violation] = []
    for path, tree in trees.items():
        if path in pyproject_exempt:
            continue
        is_test_file = "tests" in path.parts or path.name.startswith("test_")
        reads_own_doc = signals[path].reads_own_doc
        for node in ast.walk(tree):
            if isinstance(node, Documented):
                violations.extend(_check_node(path, node, is_test_file, ctx, reads_own_doc))
    return violations
