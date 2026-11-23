"""The alert-metric contract passes on the real tree and fails on a rule nothing can fire.

Each fixture is a miniature repo: one alert rule, the Python or TypeScript that
registers its metric, and the production code that records it or does not.
"""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_alert_metric_contract as contract
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

RULE = """\
apiVersion: 1
groups:
  - orgId: 1
    name: fixture
    folder: GAIA
    interval: 1m
    rules:
      - uid: gaia-fixture
        title: Fixture
        condition: C
        data:
          - refId: A
            datasourceUid: prometheus
            model: {{ refId: A, expr: '{expr}', instant: true }}
          - refId: B
            datasourceUid: __expr__
            model: {{ refId: B, type: reduce, expression: A, reducer: last }}
          - refId: C
            datasourceUid: __expr__
            model:
              refId: C
              type: threshold
              expression: B
              conditions:
                - evaluator: {{ type: gt, params: [0] }}
        for: 0m
"""

METRICS = """\
from prometheus_client import Counter, Histogram

from app.registry import _register_once

ORDERS_TOTAL = _register_once(
    "gaia_orders_total",
    lambda: Counter(name="gaia_orders_total", documentation="orders", labelnames=("outcome",)),
)
ORDER_SECONDS = Histogram("gaia_order_seconds", "order duration")


def create_order_series() -> None:
    ORDERS_TOTAL.labels("ok")


def _inc(counter: Counter, outcome: str) -> None:
    counter.labels(outcome).inc()


def observe_order(outcome: str) -> None:
    _inc(ORDERS_TOTAL, outcome)
"""

CALLER = """\
from app.metrics import observe_order


def place_order() -> None:
    observe_order("ok")
"""

BOT_METRICS = """\
import { Counter, Registry } from "prom-client";

export const registry = new Registry();

const outboundTotal = new Counter({
  name: "gaia_bot_outbound_total",
  help: "deliveries",
  registers: [registry],
});

outboundTotal.inc({ outcome: "ok" }, 0);

export function recordOutbound(outcome: string): void {
  outboundTotal.inc({ outcome });
}
"""

BOT_CALLER = """\
import { recordOutbound } from "../metrics";

export function deliver(): void {
  recordOutbound("ok");
}
"""


def _repo(root: Path, expr: str, files: dict[str, str]) -> Path:
    rules = root / contract.RULES_FILE
    rules.parent.mkdir(parents=True)
    rules.write_text(RULE.format(expr=expr))
    (root / "libs/shared/ts/src").mkdir(parents=True)
    (root / "apps/bots").mkdir(parents=True)
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
    return root


def _details(repo: Path) -> list[str]:
    return [violation.detail for violation in contract.check(repo)]


@pytest.fixture(autouse=True)
def _no_exporter_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contract, "EXPORTER_METRIC_ALLOWLIST", frozenset())


def test_the_real_tree_holds_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    assert contract.check(REPO_ROOT) == []


def test_a_recorded_metric_passes(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        'sum(increase(gaia_orders_total{job="gaia-api"}[1h]))',
        {"apps/api/app/metrics.py": METRICS, "apps/api/app/orders.py": CALLER},
    )
    assert _details(repo) == []


def test_a_rule_on_an_unregistered_metric_fails(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "sum(increase(gaia_order_total[1h]))",
        {"apps/api/app/metrics.py": METRICS, "apps/api/app/orders.py": CALLER},
    )
    assert _details(repo) == [
        "gaia-fixture queries gaia_order_total, which no code in this repo registers"
    ]


@pytest.mark.parametrize(
    "others",
    [
        pytest.param({}, id="no caller at all"),
        pytest.param(
            {"apps/api/app/orders.py": "from app.metrics import observe_order\n"},
            id="imported but never called",
        ),
        pytest.param({"apps/api/tests/test_orders.py": CALLER}, id="called only by a test"),
        pytest.param(
            {
                "apps/api/app/startup.py": (
                    "from app.metrics import create_order_series\n\n\n"
                    "def boot() -> None:\n    create_order_series()\n"
                )
            },
            id="only created at zero",
        ),
    ],
)
def test_a_registered_metric_nothing_records_fails(tmp_path: Path, others: dict[str, str]) -> None:
    repo = _repo(
        tmp_path,
        "sum(increase(gaia_orders_total[1h]))",
        {"apps/api/app/metrics.py": METRICS, **others},
    )
    assert _details(repo) == [
        "gaia-fixture queries gaia_orders_total, registered at apps/api/app/metrics.py:5 "
        "but recorded by no production code"
    ]


def test_a_collector_recorded_from_another_module_passes_by_its_sample_name(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "histogram_quantile(0.95, sum by (le) (rate(gaia_order_seconds_bucket[5m])))",
        {
            "apps/api/app/metrics.py": METRICS,
            "apps/api/app/orders.py": (
                "from app.metrics import ORDER_SECONDS\n\n\n"
                "def place_order() -> None:\n    ORDER_SECONDS.observe(1.0)\n"
            ),
        },
    )
    assert _details(repo) == []


def test_a_reexported_helper_counts_as_recorded(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "sum(increase(gaia_orders_total[1h]))",
        {
            "apps/api/app/billing/__init__.py": "from app.billing.metrics import observe_order\n",
            "apps/api/app/billing/metrics.py": METRICS,
            "apps/api/app/orders.py": CALLER.replace("app.metrics", "app.billing"),
        },
    )
    assert _details(repo) == []


def test_a_tally_from_collections_is_not_a_collector(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "sum(gaia_words_total)",
        {
            "apps/api/app/words.py": (
                "from collections import Counter\n\n"
                'WORDS = Counter("gaia_words_total")\n\n\n'
                "def count() -> None:\n    WORDS.update('a')\n"
            )
        },
    )
    assert _details(repo) == [
        "gaia-fixture queries gaia_words_total, which no code in this repo registers"
    ]


def test_an_exporter_metric_needs_its_allowlist_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, "pg_up", {})
    assert _details(repo) == ["gaia-fixture queries pg_up, which no code in this repo registers"]
    monkeypatch.setattr(contract, "EXPORTER_METRIC_ALLOWLIST", frozenset({"pg_up"}))
    assert _details(repo) == []


def test_an_allowlist_entry_no_rule_queries_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract, "EXPORTER_METRIC_ALLOWLIST", frozenset({"pg_up", "redis_up"}))
    assert _details(_repo(tmp_path, "pg_up", {})) == [
        "EXPORTER_METRIC_ALLOWLIST lists redis_up, which no rule queries"
    ]


def test_a_bot_metric_recorded_by_an_adapter_passes(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        'sum(increase(gaia_bot_outbound_total{job="bots"}[1h]))',
        {
            "libs/shared/ts/src/bots/metrics.ts": BOT_METRICS,
            "apps/bots/telegram/src/adapter.ts": BOT_CALLER,
        },
    )
    assert _details(repo) == []


@pytest.mark.parametrize(
    "others",
    [
        pytest.param({}, id="only zeroed at load"),
        pytest.param(
            {"apps/bots/telegram/src/adapter.ts": 'import { recordOutbound } from "../metrics";\n'},
            id="imported but never called",
        ),
        pytest.param(
            {"apps/bots/__tests__/adapter.test.ts": BOT_CALLER}, id="called only by a test"
        ),
    ],
)
def test_a_bot_metric_nothing_records_fails(tmp_path: Path, others: dict[str, str]) -> None:
    repo = _repo(
        tmp_path,
        "sum(increase(gaia_bot_outbound_total[1h]))",
        {"libs/shared/ts/src/bots/metrics.ts": BOT_METRICS, **others},
    )
    assert _details(repo) == [
        "gaia-fixture queries gaia_bot_outbound_total, registered at "
        "libs/shared/ts/src/bots/metrics.ts:5 but recorded by no production code"
    ]


def test_main_exits_nonzero_and_names_the_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, "sum(gaia_missing_total)", {})
    assert contract.main(["--root", str(repo)]) == 1
    assert "gaia-fixture queries gaia_missing_total" in capsys.readouterr().err
