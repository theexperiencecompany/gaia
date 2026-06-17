"""Benchmark runner: retain turns then probe, one fresh user_id per scenario.

Temporal injection:
  ``ingestion.retain`` captures ``datetime.now(UTC)`` at the top of the
  function — there is no ``occurred_at`` parameter.  We monkeypatch
  ``app.memory.ingestion.datetime`` so that each turn is stamped at
  ``base_date + timedelta(days=day_offset)``.  The patch is applied
  per-turn and restored immediately after, keeping the surrounding async
  machinery unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from typing import Any
import unittest.mock
import uuid

from app.constants.memory import MemorySourceType
from app.memory import ingestion
from app.memory.engine import memory_engine

from .dataset import SCENARIOS

BASE_DATE = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)  # base "today" for all runs

# How many scenarios to run in a single benchmark pass.
# All 40+ scenarios are defined in dataset.py; set this lower to stay inside
# the 8-minute wall-clock budget (ingestion is ~3-5 s per turn due to LLM calls).
MAX_SCENARIOS = 40


def _make_fake_datetime(target: datetime) -> type:
    """Return a drop-in replacement for the ``datetime`` class used in ingestion.py.

    ``datetime.now(UTC)`` must return ``target`` while everything else
    (``datetime.fromisoformat``, ``datetime.utcnow``, etc.) delegates to the
    real class.
    """

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return target.replace(tzinfo=tz) if tz is not None else target

    return _FakeDatetime


async def _retain_at(
    user_id: str,
    messages: list[dict[str, str]],
    turn_date: datetime,
) -> None:
    """Retain a single-turn message list, stamped at turn_date."""
    fake_dt = _make_fake_datetime(turn_date)
    with unittest.mock.patch.object(ingestion, "datetime", fake_dt):
        await ingestion.retain(
            user_id=user_id,
            messages=messages,
            source_type=MemorySourceType.CONVERSATION,
        )


def _extract_text(result: Any) -> str:
    """Pull plain text out of a MemorySearchResult (or any fallback)."""
    if hasattr(result, "memories"):
        return " | ".join(m.content for m in result.memories)
    if isinstance(result, list):
        parts = []
        for item in result:
            if hasattr(item, "content"):
                parts.append(item.content)
            elif isinstance(item, str):
                parts.append(item)
        return " | ".join(parts)
    return str(result)


def _score_probe(recalled_text: str, probe: dict) -> tuple[bool, list[str], list[str]]:
    """Return (passed, missing_terms, forbidden_found)."""
    lower = recalled_text.lower()

    missing = [term for term in probe["must_contain"] if term.lower() not in lower]
    forbidden = [term for term in probe["must_not_contain"] if term.lower() in lower]

    is_negative = probe.get("is_negative", False)
    if is_negative:
        # Negative abstention: pass when recalled text is short / empty.
        # We penalise if the engine returns more than 200 chars of fabricated content.
        passed = len(recalled_text.strip()) < 200
    else:
        passed = len(missing) == 0 and len(forbidden) == 0

    return passed, missing, forbidden


async def run_scenario(scenario: dict) -> list[dict]:
    """Run one scenario end-to-end with an isolated user_id."""
    user_id = str(uuid.uuid4())
    results: list[dict] = []

    try:
        # ── Ingestion phase ──────────────────────────────────────────────
        # Group consecutive turns that share the same day_offset into one
        # retain() call (realistic: a whole conversation in one session).
        current_offset: int | None = None
        session_messages: list[dict[str, str]] = []

        for turn in scenario["turns"]:
            offset = turn.get("day_offset", 0)
            if current_offset is None:
                current_offset = offset
            if offset != current_offset:
                # Flush previous session
                turn_date = BASE_DATE + timedelta(days=current_offset)
                await _retain_at(user_id, session_messages, turn_date)
                session_messages = []
                current_offset = offset
            session_messages.append({"role": turn["role"], "content": turn["content"]})

        if session_messages and current_offset is not None:
            turn_date = BASE_DATE + timedelta(days=current_offset)
            await _retain_at(user_id, session_messages, turn_date)

        # ── Probe phase ──────────────────────────────────────────────────
        for probe in scenario["probes"]:
            t0 = time.perf_counter()
            # Pass user_id and query as positional args: the @Cacheable key
            # generator reads args[0]/args[1] and fails if they're kwargs.
            recalled = await memory_engine.recall(user_id, probe["query"])
            latency = time.perf_counter() - t0

            recalled_text = _extract_text(recalled)
            passed, missing, forbidden = _score_probe(recalled_text, probe)

            results.append(
                {
                    "scenario_id": scenario["id"],
                    "category": scenario["category"],
                    "probe": probe["query"],
                    "description": probe["description"],
                    "passed": passed,
                    "latency_s": round(latency, 3),
                    "recalled_text": recalled_text[:2000],
                    "must_contain": probe["must_contain"],
                    "must_not_contain": probe["must_not_contain"],
                    "missing_terms": missing,
                    "forbidden_found": forbidden,
                    "is_negative": probe.get("is_negative", False),
                }
            )

    except Exception as exc:  # noqa: BLE001
        # Capture harness errors as failed probes so the report stays complete.
        for probe in scenario["probes"]:
            results.append(
                {
                    "scenario_id": scenario["id"],
                    "category": scenario["category"],
                    "probe": probe["query"],
                    "description": probe["description"],
                    "passed": False,
                    "latency_s": 0.0,
                    "recalled_text": f"[ERROR: {exc}]",
                    "must_contain": probe["must_contain"],
                    "must_not_contain": probe["must_not_contain"],
                    "missing_terms": probe["must_contain"],
                    "forbidden_found": [],
                    "is_negative": probe.get("is_negative", False),
                }
            )
    finally:
        try:
            await memory_engine.delete_all(user_id=user_id)
        except Exception:  # noqa: BLE001
            pass

    return results


async def run_all_scenarios(
    scenarios: list[dict] | None = None,
    max_scenarios: int = MAX_SCENARIOS,
) -> list[dict]:
    """Run all (or a capped subset of) scenarios sequentially and return results."""
    pool = scenarios if scenarios is not None else SCENARIOS
    pool = pool[:max_scenarios]

    all_results: list[dict] = []
    total = len(pool)
    for idx, scenario in enumerate(pool, 1):
        print(f"  [{idx:02d}/{total:02d}] {scenario['id']} ({scenario['category']}) …", flush=True)
        t0 = time.perf_counter()
        results = await run_scenario(scenario)
        elapsed = time.perf_counter() - t0
        passed = sum(1 for r in results if r["passed"])
        total_probes = len(results)
        print(
            f"         → {passed}/{total_probes} probes passed  ({elapsed:.1f}s)",
            flush=True,
        )
        all_results.extend(results)

    return all_results
