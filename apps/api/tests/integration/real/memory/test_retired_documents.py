"""Core documents of a retired type (insights_md, removed in #1094) crash every read until dropped."""

from collections.abc import AsyncGenerator
import uuid

import pytest
from scripts.drop_retired_memory_documents import drop_retired_documents
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from app.constants.memory import MemoryDocType
from app.memory import management, pg_store
from app.memory.pg_store._session import memory_session
from app.models.memory_db_models import MemoryDocument

_LEGACY_INSIGHTS = "insights_md"


@pytest.fixture
async def legacy_user(pg_engine: AsyncEngine) -> AsyncGenerator[str, None]:
    """Seed a user with a legacy insights_md row next to a live user_md."""
    user_id = f"test-mem-{uuid.uuid4().hex[:12]}"
    async with memory_session() as session:
        session.add_all(
            [
                MemoryDocument(user_id=user_id, doc_type=_LEGACY_INSIGHTS, content="# Insights"),
                MemoryDocument(user_id=user_id, doc_type=MemoryDocType.USER_MD, content="# User"),
            ]
        )
        await session.commit()
    yield user_id
    async with memory_session() as session:
        await session.execute(delete(MemoryDocument).where(MemoryDocument.user_id == user_id))
        await session.commit()


async def test_a_dry_run_keeps_the_retired_row_and_applying_drops_it(legacy_user: str) -> None:
    """One test, not two: an apply on another xdist worker would delete a dry run's seeded row."""
    planned = await drop_retired_documents(apply=False)

    assert [row.doc_type for row in planned if row.user_id == legacy_user] == [_LEGACY_INSIGHTS]
    remaining = await pg_store.get_documents(legacy_user)
    assert sorted(row.doc_type for row in remaining) == [_LEGACY_INSIGHTS, MemoryDocType.USER_MD]

    dropped = await drop_retired_documents(apply=True)

    assert [(row.user_id, row.doc_type) for row in dropped if row.user_id == legacy_user] == [
        (legacy_user, _LEGACY_INSIGHTS)
    ]
    overview = await management.get_overview(legacy_user)
    assert [preview.doc_type for preview in overview.documents] == [MemoryDocType.USER_MD]
