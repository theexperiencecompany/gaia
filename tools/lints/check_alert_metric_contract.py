#!/usr/bin/env python3
"""Alert-rule metric contract: a rule may only watch a metric something emits.

Every metric an alert rule queries must be one of two things. Either GAIA's own
code registers it (a prometheus_client collector in the API, the worker or the
voice agent; a prom-client one in the bots) AND production code records it, or
it is listed in EXPORTER_METRIC_ALLOWLIST as a series an exporter owns.

Recorded means an inc/observe/set on the collector that production code can
reach: in a function outside the module that defines the collector, or in a
helper of that module which another production module references. An import is
not a reference, a test is not production, and creating a series at zero is not
recording. That last distinction is the point: on 2026-11-21 a refactor deleted
every caller of the chat metric helpers, the collectors stayed registered and
zero-created, and four rules watched flat series with noDataState OK.

Usage::

    uv run --frozen --no-build --isolated --only-group harness python3 tools/lints/check_alert_metric_contract.py

Needs PyYAML and promql-parser, which the harness dependency group provides.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from _common import Violation, iter_python_files, report_rule
import promql_parser

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "alert-rules"))

import extract_promql

RULE = "alert-metric-contract"
WHY = (
    "a rule on a metric nothing records provisions cleanly, never fires and reads as "
    "coverage — the alert is gone and nothing says so"
)
DOC = "tools/lints/README.md#alert-metric-contract"

RULES_FILE = Path("infra/docker/observability/grafana/provisioning/alerting/alert-rules.yaml")
#: Source roots whose top-level packages are importable by name (apps/api/app is `app`).
PYTHON_ROOTS = ("apps/api", "apps/voice-agent")
PYTHON_PACKAGES = ("app", "src")
TS_ROOTS = ("libs/shared/ts/src", "apps/bots")
TS_SKIPPED_DIRS = frozenset({"node_modules", "dist", "__tests__"})

# Series an exporter owns, which no code in this repo can prove. Adding one means
# proving the pinned exporter emits it (infra/docker/observability/CLAUDE.md, step 1).
EXPORTER_METRIC_ALLOWLIST: frozenset[str] = frozenset(
    {
        "up",  # Prometheus: one per scrape target
        "http_requests_total",  # prometheus-fastapi-instrumentator on the API
        "http_request_duration_seconds_bucket",  # prometheus-fastapi-instrumentator
        "http_request_duration_seconds_count",  # prometheus-fastapi-instrumentator
        "probe_success",  # blackbox_exporter: every probe job
        "probe_ssl_earliest_cert_expiry",  # blackbox_exporter: TLS probes
        "node_filesystem_avail_bytes",  # node_exporter
        "node_filesystem_size_bytes",  # node_exporter
        "node_filesystem_files",  # node_exporter
        "node_filesystem_files_free",  # node_exporter
        "node_memory_MemAvailable_bytes",  # node_exporter
        "node_memory_MemTotal_bytes",  # node_exporter
        "container_start_time_seconds",  # cadvisor
        "container_oom_events_total",  # cadvisor
        "pg_up",  # postgres_exporter: its own connect result
        "pg_stat_activity_count",  # postgres_exporter
        "pg_settings_max_connections",  # postgres_exporter
        "redis_up",  # redis_exporter: its own connect result
        "redis_memory_used_bytes",  # redis_exporter
        "redis_memory_max_bytes",  # redis_exporter
        "redis_evicted_keys_total",  # redis_exporter
        "redis_rdb_last_bgsave_status",  # redis_exporter
        "redis_aof_last_write_status",  # redis_exporter
        "rabbitmq_queue_messages_ready",  # RabbitMQ's prometheus plugin
        "rabbitmq_queue_consumers",  # RabbitMQ's prometheus plugin
    }
)

COLLECTOR_SAMPLES = {
    "Counter": ("_total",),
    "Gauge": ("",),
    "Histogram": ("_bucket", "_count", "_sum"),
    "Summary": ("_count", "_sum"),
}
PY_RECORDERS = frozenset(
    {"inc", "dec", "set", "observe", "time", "set_to_current_time", "count_exceptions"}
)
TS_COLLECTOR = re.compile(
    r"(?:const|let)\s+(\w+)\s*=\s*new\s+(Counter|Gauge|Histogram|Summary)\s*\(\s*\{\s*name:\s*\"([^\"]+)\""
)
TS_COLLECTOR_CALL = re.compile(r"\bnew\s+(?:Counter|Gauge|Histogram|Summary)\s*\(")
TS_FUNCTION = re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE)
TS_RECORDERS = "inc|dec|set|observe|startTimer|setToCurrentTime"

Symbol = tuple[str, str]


@dataclass(frozen=True)
class Metric:
    """One registered collector: where it is defined and whether production code records it."""

    name: str
    kind: str
    path: Path
    line: int
    recorded: bool

    def samples(self) -> Iterator[str]:
        """Yield the series names the collector exposes."""
        base = self.name.removesuffix("_total") if self.kind == "Counter" else self.name
        for suffix in COLLECTOR_SAMPLES[self.kind]:
            yield base + suffix


@dataclass
class _Scope:
    """A top-level function or method: the symbols it references and the collectors it records."""

    references: set[Symbol]
    records: set[Symbol]


@dataclass
class _Module:
    name: str
    path: Path
    tree: ast.Module
    imports: dict[str, Symbol]
    defined: set[str]
    scopes: dict[str, _Scope]
    toplevel: set[Symbol]


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(tree: ast.Module, module: str, is_package: bool) -> dict[str, Symbol]:
    """Map each imported local name to (module, attribute); a module import has attribute ''."""
    package = module.split(".") if is_package else module.split(".")[:-1]
    found: dict[str, Symbol] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            source = ".".join([*base, *(node.module.split(".") if node.module else [])])
            for alias in node.names:
                found[alias.asname or alias.name] = (source, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    found[alias.asname] = (alias.name, "")
    return found


def _functions(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield f"{node.name}.{item.name}", item


class _Program:
    """Every production Python module, with names resolved across imports and re-exports."""

    def __init__(self, repo: Path) -> None:
        self.modules: dict[str, _Module] = {}
        for root in PYTHON_ROOTS:
            packages = [repo / root / package for package in PYTHON_PACKAGES]
            for path in iter_python_files([p for p in packages if p.is_dir()]):
                name = _module_name(repo / root, path)
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                self.modules[name] = _Module(
                    name=name,
                    path=path,
                    tree=tree,
                    imports=_imports(tree, name, path.name == "__init__.py"),
                    defined={
                        target.id
                        for node in tree.body
                        for target in _assigned(node)
                        if isinstance(target, ast.Name)
                    }
                    | {
                        node.name
                        for node in tree.body
                        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                    },
                    scopes={},
                    toplevel=set(),
                )
        for module in self.modules.values():
            self._index(module)

    def resolve(self, module: _Module, name: str) -> Symbol | None:
        """Return the (module, symbol) a local name denotes, following re-exports to the definition."""
        symbol: Symbol | None = (
            (module.name, name) if name in module.defined else module.imports.get(name)
        )
        for _ in range(len(self.modules)):
            if symbol is None:
                return None
            source, attribute = symbol
            if f"{source}.{attribute}" in self.modules:
                return (f"{source}.{attribute}", "")
            owner = self.modules.get(source)
            if owner is None or attribute in owner.defined or attribute == "":
                return symbol
            symbol = owner.imports.get(attribute)
        return None

    def _target(self, module: _Module, node: ast.expr) -> Symbol | None:
        """Resolve a Name, or an attribute of an imported module, to its definition."""
        if isinstance(node, ast.Name):
            return self.resolve(module, node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = self.resolve(module, node.value.id)
            if base is not None and base[1] == "" and base[0] in self.modules:
                return self.resolve(self.modules[base[0]], node.attr)
        return None

    def _index(self, module: _Module) -> None:
        in_function: set[int] = set()
        for name, function in _functions(module.tree):
            scope = _Scope(references=set(), records=set())
            for node in ast.walk(function):
                in_function.add(id(node))
                self._visit(module, node, scope)
            module.scopes[name] = scope
        outside = _Scope(references=set(), records=set())
        for node in ast.walk(module.tree):
            if id(node) not in in_function:
                self._visit(module, node, outside)
        module.toplevel = outside.references

    def _visit(self, module: _Module, node: ast.AST, scope: _Scope) -> None:
        if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load):
            target = self._target(module, node)
            if target is not None:
                scope.references.add(target)
        if not isinstance(node, ast.Call):
            return
        if isinstance(node.func, ast.Attribute) and node.func.attr in PY_RECORDERS:
            receiver = node.func.value
            while (
                isinstance(receiver, ast.Call)
                and isinstance(receiver.func, ast.Attribute)
                and receiver.func.attr == "labels"
            ):
                receiver = receiver.func.value
            target = self._target(module, receiver)
            if target is not None:
                scope.records.add(target)
        # A collector handed to a helper of the same module (_observe(X, ...)) is recorded there.
        callee = self._target(module, node.func)
        if callee is not None and callee[0] == module.name:
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                target = self._target(module, argument)
                if target is not None:
                    scope.records.add(target)

    def recorded(self, collector: Symbol) -> bool:
        """Whether a function production code can reach records this collector."""
        home = self.modules[collector[0]]
        for module in self.modules.values():
            if module is not home and any(
                collector in scope.records for scope in module.scopes.values()
            ):
                return True
        live = {
            symbol
            for module in self.modules.values()
            if module is not home
            for scope in [*module.scopes.values(), _Scope(module.toplevel, set())]
            for symbol in scope.references
            if symbol[0] == home.name
        }
        pending = list(live)
        while pending:
            scope = home.scopes.get(pending.pop()[1])
            if scope is None:
                continue
            if collector in scope.records:
                return True
            for symbol in scope.references - live:
                if symbol[0] == home.name:
                    live.add(symbol)
                    pending.append(symbol)
        return False


def _assigned(node: ast.stmt) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def _collector_call(module: _Module, value: ast.expr | None) -> tuple[str, ast.Call] | None:
    """Return (kind, constructor call) when value builds a prometheus_client collector."""
    if not isinstance(value, ast.Call):
        return None
    if isinstance(value.func, ast.Name) and value.func.id == "_register_once":
        factory = value.args[1] if len(value.args) > 1 else None
        return _collector_call(module, factory.body if isinstance(factory, ast.Lambda) else None)
    if isinstance(value.func, ast.Name):
        source = module.imports.get(value.func.id)
        if (
            source is not None
            and source[0] == "prometheus_client"
            and source[1] in COLLECTOR_SAMPLES
        ):
            return source[1], value
    return None


def python_metrics(repo: Path) -> tuple[list[Metric], list[Violation]]:
    """Return every collector production Python registers, and each one whose name is not a literal."""
    program = _Program(repo)
    metrics: list[Metric] = []
    unreadable: list[Violation] = []
    for module in program.modules.values():
        for node in module.tree.body:
            targets = [target for target in _assigned(node) if isinstance(target, ast.Name)]
            built = _collector_call(module, getattr(node, "value", None))
            if built is None or not targets:
                continue
            kind, call = built
            named = next(
                (keyword.value for keyword in call.keywords if keyword.arg == "name"),
                call.args[0] if call.args else None,
            )
            if not isinstance(named, ast.Constant) or not isinstance(named.value, str):
                unreadable.append(
                    Violation(
                        module.path,
                        node.lineno,
                        f"the {kind} assigned to {targets[0].id} has no literal name",
                        "name the collector with a string literal so the contract can read it",
                    )
                )
                continue
            metrics.append(
                Metric(
                    name=named.value,
                    kind=kind,
                    path=module.path,
                    line=node.lineno,
                    recorded=program.recorded((module.name, targets[0].id)),
                )
            )
    return metrics, unreadable


def _ts_files(repo: Path) -> list[Path]:
    return sorted(
        path
        for root in TS_ROOTS
        for path in (repo / root).rglob("*.ts")
        if not TS_SKIPPED_DIRS & set(path.parts) and not path.name.endswith((".test.ts", ".d.ts"))
    )


def ts_metrics(repo: Path) -> tuple[list[Metric], list[Violation]]:
    """Return every prom-client collector the bots register, and each one this cannot read."""
    sources = {path: path.read_text(encoding="utf-8") for path in _ts_files(repo)}
    metrics: list[Metric] = []
    unreadable: list[Violation] = []
    for path, source in sources.items():
        if "prom-client" not in source:
            continue
        collectors = list(TS_COLLECTOR.finditer(source))
        if len(collectors) != len(TS_COLLECTOR_CALL.findall(source)):
            unreadable.append(
                Violation(
                    path,
                    1,
                    'a prom-client collector here is not `const x = new Kind({ name: "..."`',
                    "declare each collector as a const with a literal name first",
                )
            )
        starts = [match.start() for match in TS_FUNCTION.finditer(source)]
        functions = {
            match.group(1): source[match.start() : end]
            for match, end in zip(
                TS_FUNCTION.finditer(source), [*starts[1:], len(source)], strict=True
            )
        }
        others = "\n".join(
            line
            for other, text in sources.items()
            if other != path
            for line in text.splitlines()
            if not line.lstrip().startswith(("import ", "export "))
        )
        for match in collectors:
            variable, kind, name = match.groups()
            records = re.compile(rf"\b{variable}\s*\.\s*(?:{TS_RECORDERS})\s*\(")
            recorded = any(
                records.search(body) and re.search(rf"\b{function}\s*\(", others)
                for function, body in functions.items()
            )
            metrics.append(
                Metric(name, kind, path, source.count("\n", 0, match.start()) + 1, recorded)
            )
    return metrics, unreadable


def queried_metrics(rules_file: Path) -> dict[str, list[str]]:
    """Return each rule uid's queried series names, in query order."""
    queried: dict[str, list[str]] = {}
    for group in extract_promql.extract(rules_file)["groups"]:
        for rule in group["rules"]:
            names: list[str] = []

            def collect(node: object, names: list[str] = names) -> None:
                if isinstance(node, promql_parser.VectorSelector):
                    names.append(node.name or "")

            promql_parser.walk(promql_parser.parse(rule["expr"]), collect)
            queried[rule["alert"]] = names
    return queried


def check(repo: Path) -> list[Violation]:
    """Return every rule that queries a metric nothing registers or records, and every stale allowlist entry."""
    rules_file = repo / RULES_FILE
    python, unreadable_python = python_metrics(repo)
    typescript, unreadable_ts = ts_metrics(repo)
    by_sample = {sample: metric for metric in [*python, *typescript] for sample in metric.samples()}
    lines = rules_file.read_text(encoding="utf-8").splitlines()
    violations = [*unreadable_python, *unreadable_ts]
    used: set[str] = set()
    for uid, names in queried_metrics(rules_file).items():
        line = next((n for n, text in enumerate(lines, 1) if text.strip() == f"- uid: {uid}"), 1)
        for name in dict.fromkeys(names):
            if name in EXPORTER_METRIC_ALLOWLIST:
                used.add(name)
                continue
            metric = by_sample.get(name)
            if not name:
                detail = f"{uid} selects a series without naming its metric"
                fix = "name the metric in the selector: metric{...}, not {__name__=...}"
            elif metric is None:
                detail = f"{uid} queries {name}, which no code in this repo registers"
                fix = (
                    "fix the name, or register and record the metric; only a series an exporter "
                    "owns goes in EXPORTER_METRIC_ALLOWLIST, once it is proven to exist"
                )
            elif not metric.recorded:
                where = f"{metric.path.relative_to(repo).as_posix()}:{metric.line}"
                detail = f"{uid} queries {name}, registered at {where} but recorded by no production code"
                fix = "record it where the action it counts ends, or delete the rule and the metric"
            else:
                continue
            violations.append(Violation(rules_file, line, detail, fix))
    for name in sorted(EXPORTER_METRIC_ALLOWLIST - used):
        violations.append(
            Violation(
                Path(__file__),
                1,
                f"EXPORTER_METRIC_ALLOWLIST lists {name}, which no rule queries",
                "delete the entry",
            )
        )
    return violations


def main(argv: list[str]) -> int:
    """Report every contract violation; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        violations = check(args.root.resolve())
    except (extract_promql.RuleShapeError, ValueError) as err:
        print(f"\n✗ {RULE} — cannot read the rules: {err}", file=sys.stderr)
        return 1
    if violations:
        report_rule(RULE, WHY, DOC, violations)
        return 1
    print(
        f"{RULE}: every metric the alert rules query is registered and recorded, or an exporter's"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
