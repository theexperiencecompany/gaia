"""Episodic journal tests — appends, day rollover, range reads, recall.

Past days are seeded through the production store function
(``pg_store.append_episode_entries``) instead of freezing the clock: a row
for an earlier date with no summary is exactly the state a real rollover
sees, so ``retain`` can be exercised unmodified with ``datetime.now``.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.constants.memory import CHROMA_MEMORY_EPISODES_COLLECTION, MemorySourceType
from app.memory import pg_store
from app.memory.engine import memory_engine
from app.memory.schemas import EpisodeSummary, ExtractedMemoryBatch
from tests.memory.llm import FakeMemoryLLM, make_batch
from tests.memory.store import chroma_user_vector_ids, fetch_episode_rows

pytestmark = pytest.mark.memory


async def _retain_entries(user_id: str, fake_llm: FakeMemoryLLM, entries: list[str]) -> None:
    fake_llm.respond(ExtractedMemoryBatch, make_batch(entries=entries))
    await memory_engine.retain(
        user_id,
        [{"role": "user", "content": "transcript"}],
        source_type=MemorySourceType.CONVERSATION,
    )


async def test_entries_append_across_retains_same_day_in_order(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain_entries(
        memory_user, fake_llm, ["Asked GAIA to plan the week", "GAIA drafted the plan"]
    )
    await _retain_entries(memory_user, fake_llm, ["Reviewed the draft plan"])

    rows = await fetch_episode_rows(memory_user)
    assert len(rows) == 1, "same-day retains must merge into one journal row"
    assert rows[0].date == datetime.now(UTC).date()
    texts = [entry["text"] for entry in rows[0].entries]
    assert texts == [
        "Asked GAIA to plan the week",
        "GAIA drafted the plan",
        "Reviewed the draft plan",
    ], "entries lost or reordered across same-day retains"
    assert all(entry["source"] == "conversation" for entry in rows[0].entries)
    assert all(entry["time"] for entry in rows[0].entries)


async def test_day_rollover_summarizes_prior_day_exactly_once(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    await pg_store.append_episode_entries(
        memory_user,
        yesterday,
        [
            {"time": "09:15", "text": "Booked flights to Lisbon", "source": "conversation"},
            {"time": "18:40", "text": "GAIA drafted the packing list", "source": "conversation"},
        ],
    )
    fake_llm.respond(
        EpisodeSummary, EpisodeSummary(summary="Booked the Lisbon trip and prepared packing.")
    )

    await _retain_entries(memory_user, fake_llm, ["Checked in for the flight"])

    episode = await pg_store.get_episode(memory_user, yesterday)
    assert episode is not None
    assert episode.summary == "Booked the Lisbon trip and prepared packing."
    # The summary is embedded for semantic episode search.
    episode_vectors = await chroma_user_vector_ids(memory_user, CHROMA_MEMORY_EPISODES_COLLECTION)
    assert f"{memory_user}:{yesterday.isoformat()}" in episode_vectors

    # A second retain the same day must NOT re-summarize the rolled-over day.
    await _retain_entries(memory_user, fake_llm, ["Landed in Lisbon"])
    assert len(fake_llm.calls_for(EpisodeSummary)) == 1, "day was summarized more than once"


async def test_get_episodes_range_is_inclusive_and_ordered(memory_user: str) -> None:
    today = datetime.now(UTC).date()
    for offset in (3, 2, 1):
        await pg_store.append_episode_entries(
            memory_user,
            today - timedelta(days=offset),
            [{"time": "12:00", "text": f"entry from {offset} days ago", "source": "conversation"}],
        )

    response = await memory_engine.get_episodes(
        memory_user, today - timedelta(days=2), today - timedelta(days=1)
    )
    assert [episode.date for episode in response.episodes] == [
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
    ], "range must be inclusive and oldest-first"


async def test_recall_episodes_finds_verbatim_entry_and_summarized_day(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    today = datetime.now(UTC).date()
    await pg_store.append_episode_entries(
        memory_user,
        today,
        [
            {
                "time": "15:00",
                "text": "Booked the dentist appointment for Friday 3pm",
                "source": "tool",
            }
        ],
    )

    # An old day far outside the 14-day verbatim window, reachable only
    # through its embedded rollover summary.
    old_day = today - timedelta(days=40)
    await pg_store.append_episode_entries(
        memory_user,
        old_day,
        [{"time": "11:00", "text": "Compared tram tours and miradouros", "source": "conversation"}],
    )
    fake_llm.respond(
        EpisodeSummary, EpisodeSummary(summary="Planned the Lisbon trip itinerary in detail.")
    )
    await memory_engine.summarize_episode(memory_user, old_day)

    verbatim_hits = await memory_engine.recall_episodes(memory_user, "dentist appointment")
    assert any(hit.date == today and "dentist appointment" in hit.text for hit in verbatim_hits), (
        f"verbatim journal entry not found: {[(h.date, h.text) for h in verbatim_hits]}"
    )

    summary_hits = await memory_engine.recall_episodes(memory_user, "trip to Lisbon")
    assert any(
        hit.date == old_day and hit.text == "Planned the Lisbon trip itinerary in detail."
        for hit in summary_hits
    ), f"summarized day not found semantically: {[(h.date, h.text) for h in summary_hits]}"


async def test_concurrent_same_day_appends_lose_nothing(memory_user: str) -> None:
    today = datetime.now(UTC).date()
    entries = [
        [{"time": "10:00", "text": f"concurrent entry {index}", "source": "conversation"}]
        for index in range(4)
    ]
    await asyncio.gather(
        *[pg_store.append_episode_entries(memory_user, today, batch) for batch in entries]
    )

    rows = await fetch_episode_rows(memory_user)
    assert len(rows) == 1, "concurrent appends must converge on one row per day"
    texts = {entry["text"] for entry in rows[0].entries}
    assert texts == {f"concurrent entry {index}" for index in range(4)}, (
        "concurrent journal appends lost entries"
    )
