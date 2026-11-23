"""extract_promql.py validates a Loki rule and names it instead of translating or dropping it."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "alert-rules"))

import extract_promql

RUNBOOK = "https://internal.lab.heygaia.io/production/runbooks"
RULES = """\
apiVersion: 1
groups:
  - orgId: 1
    name: metrics
    folder: GAIA
    interval: 1m
    rules:
      - uid: gaia-metric
        title: Metric
        condition: C
        data:
          - {{ refId: A, datasourceUid: prometheus, model: {{ refId: A, expr: up }} }}
          - {{ refId: B, datasourceUid: __expr__, model: {{ refId: B, type: reduce, expression: A, reducer: last }} }}
          - refId: C
            datasourceUid: __expr__
            model: {{ refId: C, type: threshold, expression: B, conditions: [{{ evaluator: {{ type: lt, params: [1] }} }}] }}
        for: 0m
  - orgId: 1
    name: logs
    folder: GAIA
    interval: 5m
    rules:
      - uid: gaia-log
        title: Log
        condition: C
        data:
          - {{ refId: A, datasourceUid: loki, model: {{ refId: A, expr: 'sum(count_over_time({{level="ERROR"}}[1h]))' }} }}
          - {{ refId: B, datasourceUid: __expr__, model: {{ refId: B, type: {reducer_type}, expression: A, reducer: last }} }}
          - refId: C
            datasourceUid: __expr__
            model: {{ refId: C, type: threshold, expression: B, conditions: [{{ evaluator: {{ type: gt, params: [7] }} }}] }}
        for: 0m
        annotations: {annotations}
"""


def _rules(tmp_path: Path, *, annotations: str, reducer_type: str = "reduce") -> Path:
    source = tmp_path / "alert-rules.yaml"
    source.write_text(RULES.format(annotations=annotations, reducer_type=reducer_type))
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "gaia-metric.yaml").write_text("tests: []\n")
    return source


def _run(source: Path) -> int:
    output = source.parent / "out.yaml"
    return extract_promql.main(
        ["--source", str(source), "-o", str(output), "--test-dir", str(source.parent / "tests")]
    )


def test_a_log_rule_is_validated_named_and_left_out_of_the_prometheus_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _rules(tmp_path, annotations=f"{{ runbook_url: {RUNBOOK}/gaia-log }}")

    assert _run(source) == 0

    assert "log rule, no promtool test: gaia-log" in capsys.readouterr().out
    translated = (tmp_path / "out.yaml").read_text()
    assert "gaia-metric" in translated
    assert "gaia-log" not in translated
    assert extract_promql.translate(source)[1] == ["gaia-log"]


def test_a_log_rule_without_its_runbook_link_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _rules(tmp_path, annotations="{}")

    assert _run(source) == 1
    assert (
        f"gaia-log: log rule must carry runbook_url {RUNBOOK}/gaia-log" in capsys.readouterr().err
    )


def test_a_log_rule_is_held_to_the_three_node_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _rules(
        tmp_path, annotations=f"{{ runbook_url: {RUNBOOK}/gaia-log }}", reducer_type="math"
    )

    assert _run(source) == 1
    assert "gaia-log: node 'B' is 'math'" in capsys.readouterr().err


def test_a_promtool_test_file_for_a_log_rule_is_an_orphan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _rules(tmp_path, annotations=f"{{ runbook_url: {RUNBOOK}/gaia-log }}")
    (tmp_path / "tests" / "gaia-log.yaml").write_text("tests: []\n")

    assert _run(source) == 1
    assert "test files with no matching rule (1): gaia-log" in capsys.readouterr().err
