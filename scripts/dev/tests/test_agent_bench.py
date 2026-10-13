"""agent_bench token attribution: only the bench user's traces count, whichever LangSmith path answers.

The network seams are mocked — `subprocess.run` (the langsmith CLI) and
`langsmith.Client` (the SDK). Everything above them is the real code.

Run: uv run pytest scripts/dev/tests/test_agent_bench.py -p no:xdist
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import langsmith
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_bench  # the path insert above must precede this import

START = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
END = START + timedelta(minutes=5)
BENCH_USER = "user-bench"


def _root(tokens: int, user_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        start_time=(START + timedelta(minutes=1)).replace(tzinfo=None),
        total_tokens=tokens,
        metadata={"user_id": user_id},
    )


class _FakeClient:
    def list_runs(self, **kwargs: object) -> list[SimpleNamespace]:
        return [_root(100, BENCH_USER), _root(9_000, "user-other-worktree")]


def _cli_missing(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    raise FileNotFoundError("langsmith")


def test_the_sdk_fallback_counts_only_the_bench_users_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_PROJECT", "bench")
    monkeypatch.setattr(agent_bench, "_load_api_env", lambda: None)
    monkeypatch.setattr(subprocess, "run", _cli_missing)
    monkeypatch.setattr(langsmith, "Client", _FakeClient)
    assert agent_bench._tokens_between(START, END, BENCH_USER) == 100


def test_an_unresolved_bench_user_reports_tokens_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_PROJECT", "bench")
    monkeypatch.setattr(agent_bench, "_load_api_env", lambda: None)
    monkeypatch.setattr(subprocess, "run", _cli_missing)
    monkeypatch.setattr(langsmith, "Client", _FakeClient)
    assert agent_bench._tokens_between(START, END, None) is None
