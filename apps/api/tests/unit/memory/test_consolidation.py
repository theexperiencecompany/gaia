"""Unit tests for app.memory.consolidation — what actually lands in a core document.

Postgres, the document writer and the two LLM calls are mocked; the size cap,
the retry, the fact-check and the agenda rendering under test are real.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.constants.memory import (
    AGENDA_CATEGORY_PATH,
    AGENDA_INJECTED_ITEM_CAP,
    DOCUMENT_TARGET_MAX_CHARS,
    MemoryDocType,
    MemoryKind,
    MemoryShelfLife,
    MemorySourceType,
)
from app.memory import consolidation
from app.memory.consolidation import consolidate, render_agenda_document
from app.memory.schemas import VerifiedDocument
from app.models.memory_db_models import MemoryRecord

USER = "user-1"


def make_row(content: str = "sam is vegetarian", importance: float = 0.5) -> MemoryRecord:
    row = MemoryRecord(
        user_id=USER,
        kind=MemoryKind.FACT.value,
        shelf_life=MemoryShelfLife.DURABLE.value,
        content=content,
        category_path="food-preferences",
        source_type=MemorySourceType.CONVERSATION.value,
        importance=importance,
    )
    row.id = uuid.uuid4()
    row.created_at = datetime.now(UTC)
    return row


@pytest.fixture
def boundaries() -> MagicMock:
    """Patch every I/O edge of consolidate()/render_agenda_document()."""
    mocks = MagicMock()
    mocks.rewrite = AsyncMock(return_value="# About\n- something")
    mocks.verify = AsyncMock(return_value=None)
    mocks.update_document = AsyncMock(return_value=None)
    mocks.get_document = AsyncMock(return_value=None)
    mocks.get_facts = AsyncMock(return_value=[make_row()])
    mocks.get_agenda = AsyncMock(return_value=[])
    mocks.get_entities = AsyncMock(return_value=[])
    with (
        patch.multiple(
            consolidation.pg_store,
            get_document=mocks.get_document,
            get_facts_for_consolidation=mocks.get_facts,
            get_agenda_memories=mocks.get_agenda,
            get_entities_by_type=mocks.get_entities,
        ),
        patch.multiple(
            consolidation,
            rewrite_core_document=mocks.rewrite,
            verify_core_document=mocks.verify,
            update_document=mocks.update_document,
            _get_user_name=AsyncMock(return_value="Sam"),
        ),
    ):
        yield mocks


@pytest.mark.unit
class TestDocumentSizeCap:
    async def test_a_document_within_the_cap_is_written(self, boundaries: MagicMock) -> None:
        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.update_document.await_args.args[2] == "# About\n- something"

    async def test_an_oversized_document_is_retried_with_a_trim_instruction(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.rewrite.side_effect = ["x" * (DOCUMENT_TARGET_MAX_CHARS + 1), "# Short"]

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.rewrite.await_count == 2
        retry_prompt = boundaries.rewrite.await_args.args[1]
        assert str(DOCUMENT_TARGET_MAX_CHARS) in retry_prompt
        assert boundaries.update_document.await_args.args[2] == "# Short"

    async def test_a_document_that_stays_oversized_is_rejected(self, boundaries: MagicMock) -> None:
        # The prompt asking nicely was the only enforcement, and production
        # agenda.md reached 4,886 characters against a 2,500 cap.
        boundaries.rewrite.return_value = "x" * (DOCUMENT_TARGET_MAX_CHARS + 1)

        rewritten = await consolidate(USER, [MemoryDocType.USER_MD])

        assert rewritten == []
        boundaries.update_document.assert_not_awaited()


@pytest.mark.unit
class TestVerificationPass:
    async def test_an_unsupported_line_is_struck_before_the_document_lands(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.rewrite.return_value = (
            "# About\n- Sam is vegetarian\n- Partner: Khyal Shetal (anniversary Oct 19, 2026)"
        )
        boundaries.verify.return_value = VerifiedDocument(
            content="# About\n- Sam is vegetarian",
            struck=["- Partner: Khyal Shetal (anniversary Oct 19, 2026)"],
        )

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.update_document.await_args.args[2] == "# About\n- Sam is vegetarian"

    async def test_the_source_facts_are_what_the_check_is_given(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.get_facts.return_value = [make_row("sam is vegetarian")]
        boundaries.verify.return_value = VerifiedDocument(content="# About", struck=[])

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.verify.await_args.args[1] == ["sam is vegetarian"]

    async def test_a_failed_check_keeps_the_unverified_document(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.verify.return_value = None

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.update_document.await_args.args[2] == "# About\n- something"


@pytest.mark.unit
class TestConsolidationInputs:
    async def test_only_durable_facts_reach_a_document(self, boundaries: MagicMock) -> None:
        # A value that was only true as of a moment must never be consolidated
        # into a document injected on every turn.
        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.get_facts.await_args.kwargs["shelf_life"] == (
            MemoryShelfLife.DURABLE.value
        )

    async def test_the_agenda_is_never_consolidated_by_an_llm(self, boundaries: MagicMock) -> None:
        rewritten = await consolidate(USER, [MemoryDocType.AGENDA_MD])

        assert rewritten == []
        boundaries.rewrite.assert_not_awaited()


@pytest.mark.unit
class TestRenderAgendaDocument:
    async def test_live_agenda_rows_become_the_document(self, boundaries: MagicMock) -> None:
        boundaries.get_agenda.return_value = [
            make_row("ship the billing migration"),
            make_row("file the tax return by March 3"),
        ]

        await render_agenda_document(USER)

        doc_type, content = boundaries.update_document.await_args.args[1:3]
        assert doc_type is MemoryDocType.AGENDA_MD
        assert "- ship the billing migration" in content
        assert "- file the tax return by March 3" in content

    async def test_the_injected_item_cap_is_what_bounds_the_page(
        self, boundaries: MagicMock
    ) -> None:
        await render_agenda_document(USER)

        assert boundaries.get_agenda.await_args.kwargs["limit"] == AGENDA_INJECTED_ITEM_CAP

    async def test_an_empty_agenda_still_writes_a_page(self, boundaries: MagicMock) -> None:
        # A user who closed their last loop must end up with an empty agenda,
        # not the previous version left standing.
        await render_agenda_document(USER)

        content = boundaries.update_document.await_args.args[2]
        assert "nothing open" in content


@pytest.mark.unit
class TestInferDocTypes:
    def test_an_agenda_fact_feeds_no_consolidated_document(self) -> None:
        from app.memory.schemas import ExtractedFact

        fact = ExtractedFact(
            content="owes the user a draft",
            kind=MemoryKind.FACT,
            shelf_life=MemoryShelfLife.TASK,
            category_path=AGENDA_CATEGORY_PATH,
            importance=0.5,
        )
        assert consolidation.infer_doc_types([fact]) == set()
