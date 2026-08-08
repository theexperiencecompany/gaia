"""Append-only run journal: the source of truth for every eval run.

One self-contained JSON record per completed case. A run never rewrites
history — resume reads the journal once and skips every case with a terminal
status. The HTML report and cost tables rebuild from the journal alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from typing import Any

from .types import PriceBook, ProviderPrice

TERMINAL_STATUSES = {"passed", "failed", "skipped"}


@dataclass
class RunMeta:
    run_id: str
    suite: str
    started_at: str
    provider_order: list[str] = field(default_factory=list)
    status: str = "running"
    finished_at: str | None = None
    experiment_name: str | None = None
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    excluded: str | None = None
    """Why this run's measurements must not be aggregated, or None.

    A journal is append-only and its records are never rewritten — so when a run
    is later found to have recorded something provably wrong, the honest move is
    to record *that fact* here rather than to edit the data. Aggregation skips
    the run and says so; the raw records stay on disk, auditable.
    """


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunJournal:
    """Thread-safe append-only journal backed by ``runs/<run_id>/journal.jsonl``."""

    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self.dir = runs_dir / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "journal.jsonl"
        self.meta_path = self.dir / "run.json"
        self._lock = threading.Lock()
        self._status: dict[str, str] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                rec = json.loads(line)
                self._status[rec["case_id"]] = str(rec.get("status", ""))

    def create_meta(self, meta: RunMeta) -> None:
        with self._lock:
            self.meta_path.write_text(
                json.dumps(meta.__dict__, indent=2, default=str), encoding="utf-8"
            )

    def load_meta(self) -> RunMeta | None:
        if not self.meta_path.exists():
            return None
        data = json.loads(self.meta_path.read_text())
        return RunMeta(**data)

    def update_meta(self, **updates: object) -> None:
        meta = self.load_meta()
        if meta is None:
            return
        for key, value in updates.items():
            setattr(meta, key, value)
        with self._lock:
            self.meta_path.write_text(
                json.dumps(meta.__dict__, indent=2, default=str), encoding="utf-8"
            )

    def has_terminal(self, case_id: str) -> bool:
        """Whether the case reached a real verdict, so ``--resume`` can skip it.

        An ``errored`` case is not a verdict — the agent was never measured — so
        it stays resumable rather than freezing a crash into the run's score.
        """
        return self._status.get(case_id, "") in TERMINAL_STATUSES

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._status[record["case_id"]] = str(record.get("status", ""))
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def record_for(self, case_id: str) -> dict[str, Any] | None:
        """The case's latest outcome.

        The journal is append-only, so a re-run (``--only-failed``) leaves both
        attempts on disk. Returning the first match would report the stale one,
        which is how a re-run could look like it changed nothing.
        """
        for rec in reversed(self.records()):
            if rec["case_id"] == case_id:
                return rec
        return None

    def tokens(self) -> tuple[int, int]:
        total_in = sum(int(r.get("tokens", {}).get("input", 0)) for r in self.records())
        total_out = sum(int(r.get("tokens", {}).get("output", 0)) for r in self.records())
        return total_in, total_out

    def cost_usd(self, prices: PriceBook) -> float:
        return sum(
            prices.get(r.get("provider", ""), ProviderPrice()).paid_cost(
                int((r.get("tokens") or {}).get("input", 0)),
                int((r.get("tokens") or {}).get("output", 0)),
            )
            for r in self.records()
        )
