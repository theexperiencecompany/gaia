"""The memory workspace's projection: what Postgres rows become as files on disk."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.memory import pg_store
from app.services import memory_fs


async def test_a_journal_day_projects_its_entries_and_summary_as_one_page() -> None:
    day = SimpleNamespace(
        date=date(2026, 3, 5),
        entries=[{"time": "09:00", "text": "drafted the email"}],
        summary="Busy morning.",
    )
    empty_day = SimpleNamespace(date=date(2026, 3, 4), entries=[], summary=None)
    with (
        patch.object(pg_store, "get_documents", new=AsyncMock(return_value=[])),
        patch.object(pg_store, "get_episodes_range", new=AsyncMock(return_value=[empty_day, day])),
        patch.object(pg_store, "get_all_live_memories", new=AsyncMock(return_value=[])),
    ):
        projections = await memory_fs._fetch_projections("u1")

    assert projections == [
        {
            "id": "journal:2026-03-05",
            "path": "journal/2026-03-05.md",
            "content": (
                "# 2026-03-05\n\n- 09:00 drafted the email\n\n## Summary\n\nBusy morning.\n"
            ),
        }
    ]
