#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Derive a Prometheus-native rule file from the Grafana-managed alert rules.

Usage:
    uv run tools/alert-rules/extract_promql.py -o /tmp/gaia-rules.yaml

pint only understands Prometheus rule YAML. Our rules are Grafana-managed: the
PromQL lives in the ``refId: A`` data node and the threshold in a separate
expression node, so pint cannot read them directly. This translates each Grafana
rule into one alerting rule, letting pint lint the single source of truth
without a second, hand-maintained copy of it.

Any rule that does not match the documented three-node A/B/C shape aborts the
run. A rule that quietly drops out of linting is exactly the failure mode this
exists to prevent.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Any, NoReturn

import yaml

EXPRESSION_DATASOURCE = "__expr__"
COMPARISONS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
DOC = "infra/docker/observability/CLAUDE.md → Adding an alert rule"
# Grafana `for` durations. Single-unit to keep it honest: every rule here uses
# m or h, and promtool check rules rejects garbage downstream anyway.
FOR_DURATION = re.compile(r"^\d+(ms|s|m|h|d|w|y)$")


class RuleShapeError(Exception):
    """A Grafana rule is shaped in a way the extractor cannot translate."""


def _fail(uid: str, detail: str) -> NoReturn:
    raise RuleShapeError(f"{uid}: {detail}")


def _nodes(uid: str, rule: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = rule.get("data")
    if not isinstance(data, list) or not data:
        _fail(uid, "has no data[] nodes")
    nodes: dict[str, dict[str, Any]] = {}
    for node in data:
        ref = node.get("refId")
        if not isinstance(ref, str):
            _fail(uid, "a data[] node has no refId")
        if ref in nodes:
            _fail(uid, f"data[] declares refId {ref!r} twice")
        if not isinstance(node.get("model"), dict):
            _fail(uid, f"data[] node {ref!r} has no model")
        nodes[ref] = node
    return nodes


def _query(uid: str, nodes: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Return the (refId, expr) of the rule's single datasource query node."""
    queries = [r for r, n in nodes.items() if n.get("datasourceUid") != EXPRESSION_DATASOURCE]
    if len(queries) != 1:
        _fail(
            uid,
            f"expected exactly one datasource query node, found {len(queries)} "
            f"({', '.join(queries) or 'none'})",
        )
    ref = queries[0]
    expr = nodes[ref]["model"].get("expr")
    if not isinstance(expr, str) or not expr.strip():
        _fail(uid, f"query node {ref!r} has no model.expr")
    return ref, expr.strip()


def _comparison(uid: str, nodes: dict[str, dict[str, Any]], condition: str) -> str:
    """Return the ``> 1``-style comparison the threshold node applies."""
    model = nodes[condition]["model"]
    if model.get("type") != "threshold":
        _fail(uid, f"condition {condition!r} is a {model.get('type')!r} node, not a threshold")
    conditions = model.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != 1:
        _fail(uid, f"threshold {condition!r} must hold exactly one condition")
    evaluator = conditions[0].get("evaluator", {})
    operator = COMPARISONS.get(evaluator.get("type"))
    if operator is None:
        _fail(
            uid,
            f"threshold {condition!r} uses evaluator {evaluator.get('type')!r}, which has no "
            f"PromQL equivalent here (supported: {', '.join(sorted(COMPARISONS))})",
        )
    params = evaluator.get("params")
    if not isinstance(params, list) or len(params) != 1 or isinstance(params[0], bool):
        _fail(uid, f"threshold {condition!r} must carry exactly one numeric param")
    if not isinstance(params[0], (int, float)):
        _fail(uid, f"threshold {condition!r} param {params[0]!r} is not a number")
    return f"{operator} {params[0]}"


def _assert_chains_to_query(
    uid: str, nodes: dict[str, dict[str, Any]], condition: str, query: str
) -> None:
    ref = nodes[condition]["model"].get("expression")
    for _ in range(len(nodes)):
        node = nodes.get(ref) if isinstance(ref, str) else None
        if node is None:
            _fail(uid, f"expression chain from {condition!r} references undefined node {ref!r}")
        model = node["model"]
        if model.get("type") != "reduce" or model.get("reducer") != "last":
            _fail(
                uid,
                f"node {ref!r} is {model.get('type')!r}/{model.get('reducer')!r}; only a reduce "
                "with reducer 'last' leaves the query value the threshold compares unchanged",
            )
        if ref == query:
            _fail(
                uid,
                "the threshold references the query node directly; the documented A/B/C shape "
                "requires a reduce step between them",
            )
        ref = model.get("expression")
        if ref == query:
            return
    _fail(uid, f"expression chain from {condition!r} never reaches the query node {query!r}")


def _validate_annotations(uid: str, annotations: dict[str, Any]) -> None:
    """Fail on the documented annotation-template traps.

    Grafana expands these templates itself and its error path keeps the raw
    text, so a broken one ships silently — the summary shows up verbatim in
    Slack. The fixtures cannot cover them (the extractor drops templated
    annotations for promtool), so validate the three documented traps
    structurally instead: unbalanced braces, a bare ``$values.<ref>`` piped
    into a formatter instead of ``$values.<ref>.Value``, and any ``$values`` /
    ``$labels`` reference with no ``{{ if $values ... }}`` guard for the
    DatasourceError/NoData path.
    """
    for name, value in annotations.items():
        text = str(value)
        if "{{" not in text:
            continue
        if text.count("{{") != text.count("}}"):
            _fail(uid, f"annotation {name!r} has unbalanced {{{{/}}}}")
        if re.search(r"\$values\.|\$labels\.", text) and not re.search(
            r"\{\{\s*if \$values\.", text
        ):
            _fail(
                uid,
                f"annotation {name!r} references $values/$labels with no guard "
                "({{{{ if $values.<ref> }}}})",
            )
        # Strip the guard(s); every remaining $values.<ref> must be a .Value access.
        remaining = re.sub(r"\{\{\s*if \$values\.\w+", "", text)
        for m in re.finditer(r"\$values\.\w+", remaining):
            if remaining[m.end() : m.end() + len(".Value")] != ".Value":
                _fail(
                    uid,
                    f"annotation {name!r} references {m.group()} without .Value "
                    "(the struct is not a float)",
                )


def _alerting_rule(rule: dict[str, Any]) -> dict[str, Any]:
    uid = rule.get("uid")
    if not isinstance(uid, str) or not uid:
        _fail(str(rule.get("title", "<untitled>")), "has no uid")

    nodes = _nodes(uid, rule)
    condition = rule.get("condition")
    if condition not in nodes:
        _fail(uid, f"condition {condition!r} is not a refId in data[]")
    query, expr = _query(uid, nodes)
    _assert_chains_to_query(uid, nodes, condition, query)

    duration = rule.get("for")
    if not isinstance(duration, str) or not duration:
        _fail(uid, "has no `for` (Grafana rejects the whole file without it)")
    if not FOR_DURATION.fullmatch(duration):
        _fail(uid, f"`for` value {duration!r} is not a valid Grafana duration (e.g. 5m, 24h)")

    # The query is wrapped before the comparison is appended: a bare `and`/`or`
    # at the top level binds looser than a comparison, so an unwrapped
    # `a and b > 1` would compare only `b`.
    out: dict[str, Any] = {
        "alert": uid,
        "expr": f"({expr}) {_comparison(uid, nodes, condition)}",
        "for": duration,
    }
    if rule.get("labels"):
        out["labels"] = rule["labels"]
    _validate_annotations(uid, rule.get("annotations") or {})
    # Grafana expands annotations with its own engine, whose `$values.<ref>.Value`
    # does not exist in Prometheus templates — promtool rejects the file outright
    # ("undefined variable $values"). Only literal annotations survive the
    # translation; the templated ones are Grafana's to validate.
    literal = {k: v for k, v in (rule.get("annotations") or {}).items() if "{{" not in str(v)}
    if literal:
        out["annotations"] = literal
    return out


class _BlockDumper(yaml.SafeDumper):
    """Emits multi-line PromQL as a block scalar so pint can point at a column."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_BlockDumper.add_representer(str, _represent_str)


def _check_test_coverage(test_dir: Path, rules: dict[str, Any]) -> None:
    """Fail if any rule lacks a promtool test file, or any test has no rule.

    A rule without a test is exactly the failure mode everything here guards
    against: it provisions cleanly, is never executed, and no one notices. The
    test directory is checked against the extracted uids so the coverage
    contract lives in the same tool that owns the canonical uid list.
    """
    if not test_dir.is_dir():
        _fail("test coverage", f"test directory {test_dir} does not exist")
    uids = {r["alert"] for g in rules["groups"] for r in g["rules"]}
    test_uids = {p.stem for p in test_dir.glob("*.yaml")}
    missing = sorted(uids - test_uids)
    orphaned = sorted(test_uids - uids)
    if missing or orphaned:
        detail = []
        if missing:
            detail.append(f"rules without a promtool test ({len(missing)}): {', '.join(missing)}")
        if orphaned:
            detail.append(
                f"test files with no matching rule ({len(orphaned)}): {', '.join(orphaned)}"
            )
        _fail("test coverage", "; ".join(detail))


def extract(source: Path) -> dict[str, Any]:
    """Translate the Grafana rules file into a Prometheus-native rules document.

    Every rule must match the documented A/B/C shape or the run aborts; see the
    module docstring for the contract. The returned document has the same
    ``groups`` structure as a Prometheus rule file, ready for pint/promtool.
    """
    document = yaml.safe_load(source.read_text())
    groups = document.get("groups") if isinstance(document, dict) else None
    if not isinstance(groups, list) or not groups:
        raise RuleShapeError(f"{source}: has no groups[]")

    seen: set[str] = set()
    out_groups: list[dict[str, Any]] = []
    for group in groups:
        rules = group.get("rules")
        if not isinstance(rules, list) or not rules:
            raise RuleShapeError(f"group {group.get('name')!r}: has no rules[]")
        out_rules = []
        for rule in rules:
            alerting = _alerting_rule(rule)
            if alerting["alert"] in seen:
                _fail(alerting["alert"], "uid is declared twice; the second rule overwrites it")
            seen.add(alerting["alert"])
            out_rules.append(alerting)
        out_group: dict[str, Any] = {"name": group["name"]}
        if group.get("interval"):
            out_group["interval"] = group["interval"]
        out_group["rules"] = out_rules
        out_groups.append(out_group)
    return {"groups": out_groups}


def main(argv: list[str]) -> int:
    """CLI entrypoint: extract rules and optionally check test coverage.

    Returns the process exit code: 0 on success, 1 when any rule is not
    extractable or (with ``--test-dir``) lacks a promtool test file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("infra/docker/observability/grafana/provisioning/alerting/alert-rules.yaml"),
    )
    parser.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    parser.add_argument(
        "--test-dir",
        type=Path,
        help="directory of per-rule promtool test files; every rule must have one",
    )
    args = parser.parse_args(argv)

    source = args.source.resolve()
    if not source.is_file():
        print(
            f"\n✗ alert-rule validation failed — --source {source} is not a file", file=sys.stderr
        )
        return 1
    test_dir = args.test_dir.resolve() if args.test_dir is not None else None

    try:
        rules = extract(source)
        if test_dir is not None:
            _check_test_coverage(test_dir, rules)
    except RuleShapeError as err:
        print(f"\n✗ alert-rule validation failed — {err}", file=sys.stderr)
        print(
            "\n  Every Grafana rule must match the three-node A/B/C shape so pint can lint it,\n"
            "  and every rule must have a promtool test in the --test-dir.\n"
            f"  Fix the rule, or teach {Path(__file__).name} the new shape deliberately.\n"
            f"  docs: {DOC}",
            file=sys.stderr,
        )
        return 1

    rendered = yaml.dump(
        rules, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=10_000
    )
    count = sum(len(g["rules"]) for g in rules["groups"])
    if args.output:
        args.output.write_text(rendered)
        print(f"extracted {count} alert rules from {args.source} to {args.output}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
