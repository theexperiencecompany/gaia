"""Cost and token accounting across every run journal.

Two costs are reported per suite and per provider, because they answer different
questions: **list** is what reproducing the eval costs at rack rate (comparable
to anyone else's numbers), **paid** is what the lane actually billed us after
its discount. Prices come from the provider catalog — never from a literal in
this file, which is how the old table drifted to a stale $0.15/$0.60.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from .types import PriceBook, ProviderPrice

_NO_PRICE = ProviderPrice()


@dataclass
class Spend:
    """Measured usage for one bucket (a suite, or a provider)."""

    cases: int = 0
    runs: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    list_usd: float = 0.0
    paid_usd: float = 0.0
    passed: int = 0
    graded: int = 0

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def tokens_per_case(self) -> float:
        return self.tokens / self.cases if self.cases else 0.0

    @property
    def pass_rate(self) -> float:
        """Over cases that produced an answer — errors dilute a rate, not fail it."""
        return self.passed / self.graded * 100 if self.graded else 0.0

    def add(self, record: dict[str, object], price: ProviderPrice) -> None:
        tokens = record.get("tokens")
        tokens_in = int(tokens.get("input", 0)) if isinstance(tokens, dict) else 0
        tokens_out = int(tokens.get("output", 0)) if isinstance(tokens, dict) else 0
        self.cases += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.list_usd += price.list_cost(tokens_in, tokens_out)
        self.paid_usd += price.paid_cost(tokens_in, tokens_out)
        self.passed += record.get("status") == "passed"
        self.graded += record.get("status") != "errored"


@dataclass
class Accounting:
    """Everything the journals say about usage, bucketed two ways."""

    by_suite: dict[str, Spend] = field(default_factory=dict)
    by_provider: dict[str, Spend] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> Spend:
        total = Spend()
        for spend in self.by_suite.values():
            total.cases += spend.cases
            total.runs += spend.runs
            total.tokens_in += spend.tokens_in
            total.tokens_out += spend.tokens_out
            total.list_usd += spend.list_usd
            total.paid_usd += spend.paid_usd
            total.passed += spend.passed
            total.graded += spend.graded
        return total


def accounting(runs_dir: Path, prices: PriceBook) -> Accounting:
    """Fold every journal record into per-suite and per-provider spend."""
    result = Accounting()
    for run_dir in sorted(runs_dir.iterdir()):
        journal_path = run_dir / "journal.jsonl"
        meta_path = run_dir / "run.json"
        if not run_dir.is_dir() or not journal_path.exists() or not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        suite = str(meta.get("suite", "?"))
        excluded = meta.get("excluded")
        if excluded:
            result.excluded[run_dir.name] = str(excluded)
            continue
        result.by_suite.setdefault(suite, Spend()).runs += 1
        for line in journal_path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            provider = str(record.get("provider", "?"))
            price = prices.get(provider, _NO_PRICE)
            result.by_suite[suite].add(record, price)
            result.by_provider.setdefault(provider, Spend()).add(record, price)
    return result


def project(runs_dir: Path, prices: PriceBook) -> None:
    """Print the measured spend tables."""
    books = accounting(runs_dir, prices)
    if not books.by_suite:
        print(f"no journals under {runs_dir}")
        return

    print(
        f"{'suite':<16}{'runs':>5}{'cases':>7}{'pass%':>7}"
        f"{'tokens':>12}{'tok/case':>10}{'list USD':>10}{'paid USD':>10}"
    )
    print("-" * 77)
    for suite, spend in sorted(books.by_suite.items()):
        print(
            f"{suite:<16}{spend.runs:>5}{spend.cases:>7}{spend.pass_rate:>6.1f}%"
            f"{spend.tokens:>12,}{spend.tokens_per_case / 1e3:>9,.1f}K"
            f"{spend.list_usd:>10.4f}{spend.paid_usd:>10.4f}"
        )
    total = books.total
    print("-" * 77)
    print(
        f"{'TOTAL':<16}{total.runs:>5}{total.cases:>7}{total.pass_rate:>6.1f}%"
        f"{total.tokens:>12,}{total.tokens_per_case / 1e3:>9,.1f}K"
        f"{total.list_usd:>10.4f}{total.paid_usd:>10.4f}"
    )

    print(
        f"\n{'provider':<16}{'cases':>7}{'tokens in':>13}{'tokens out':>13}{'list USD':>10}{'paid USD':>10}{'disc':>7}"
    )
    print("-" * 76)
    for provider, spend in sorted(books.by_provider.items()):
        discount = prices.get(provider, _NO_PRICE).discount_pct
        print(
            f"{provider:<16}{spend.cases:>7}{spend.tokens_in:>13,}{spend.tokens_out:>13,}"
            f"{spend.list_usd:>10.4f}{spend.paid_usd:>10.4f}{discount:>6.0f}%"
        )

    for run_id, reason in sorted(books.excluded.items()):
        print(f"\nexcluded {run_id}: {reason}")

    saved = total.list_usd - total.paid_usd
    print(
        f"\nlist {total.list_usd:.4f} USD · paid {total.paid_usd:.4f} USD · "
        f"lane discounts absorbed {saved:.4f} USD "
        f"({saved / total.list_usd * 100:.0f}%)"
        if total.list_usd
        else "\nno metered usage recorded"
    )
