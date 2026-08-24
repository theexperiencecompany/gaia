"""Unit tests for app.memory.consolidation — what actually lands in a core document.

Postgres, the document writer and the two LLM calls are mocked; the size cap,
the retry, the fact-check and the agenda rendering under test are real.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.constants.memory import (
    AGENDA_CATEGORY_PATH,
    AGENDA_INJECTED_ITEM_CAP,
    CONSOLIDATION_FACTS_LIMIT,
    DOCUMENT_TARGET_MAX_CHARS,
    MemoryDocType,
    MemoryEntityType,
    MemoryKind,
    MemoryShelfLife,
    MemorySourceType,
)
from app.memory import consolidation
from app.memory.consolidation import consolidate, render_agenda_document
from app.memory.schemas import ExtractedFact, VerifiedDocument
from app.models.memory_db_models import MemoryRecord
from tests.helpers import captured_wide_event

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
        # Exactly one retry: a third attempt would double the cost of a model
        # that is simply ignoring the cap.
        assert boundaries.rewrite.await_count == 2
        boundaries.update_document.assert_not_awaited()

    async def test_a_document_of_exactly_the_cap_is_accepted(self, boundaries: MagicMock) -> None:
        boundaries.rewrite.return_value = "x" * DOCUMENT_TARGET_MAX_CHARS

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.rewrite.await_count == 1
        assert boundaries.update_document.await_args.args[2] == "x" * DOCUMENT_TARGET_MAX_CHARS

    async def test_the_retry_names_the_cap_and_forbids_truncation(
        self, boundaries: MagicMock
    ) -> None:
        oversized = "x" * (DOCUMENT_TARGET_MAX_CHARS + 1)
        boundaries.rewrite.side_effect = [oversized, "# Short"]

        await consolidate(USER, [MemoryDocType.USER_MD])

        first_human, retry_human = (call.args[1] for call in boundaries.rewrite.await_args_list)
        assert retry_human == (
            f"{first_human}\n\n## Your previous attempt was too long\n"
            f"It was {len(oversized)} characters against a hard cap of "
            f"{DOCUMENT_TARGET_MAX_CHARS}. Rewrite it under the cap by dropping "
            "the least important bullets — do not truncate mid-sentence, and do "
            "not drop a section heading."
        )

    async def test_every_over_cap_attempt_is_reported_with_its_number(
        self, boundaries: MagicMock
    ) -> None:
        oversized = "x" * (DOCUMENT_TARGET_MAX_CHARS + 1)
        boundaries.rewrite.return_value = oversized

        async with captured_wide_event() as event:
            await consolidation._rewrite_within_cap(
                USER, MemoryDocType.USER_MD, "previous", ["## facts"], user_name="Sam"
            )

        assert event["warnings"] == [
            {
                "msg": "memory_consolidation_doc_over_cap",
                "user_id": USER,
                "doc_type": "user_md",
                "error_type": "document_over_cap",
                "chars": len(oversized),
                "cap": DOCUMENT_TARGET_MAX_CHARS,
                "attempt": attempt,
            }
            for attempt in (1, 2)
        ]


@pytest.mark.unit
class TestRewriteWithinCapInputs:
    async def test_the_rewrite_is_given_the_doc_prompt_the_inputs_and_the_owner(
        self, boundaries: MagicMock
    ) -> None:
        await consolidation._rewrite_within_cap(
            USER, MemoryDocType.MEMORY_MD, "previous", ["## facts"], user_name="Sam"
        )

        call = boundaries.rewrite.await_args
        assert call.args == (
            consolidation._system_prompt(MemoryDocType.MEMORY_MD, "Sam"),
            consolidation._format_inputs("previous", ["## facts"]),
        )
        assert call.kwargs == {"user_id": USER}

    async def test_an_empty_rewrite_is_rejected_rather_than_written(
        self, boundaries: MagicMock
    ) -> None:
        # Whitespace is not a document: writing it would replace a good page
        # with a blank one on every subsequent turn.
        boundaries.rewrite.return_value = "   \n  "

        assert (
            await consolidation._rewrite_within_cap(
                USER, MemoryDocType.USER_MD, "previous", ["## facts"], user_name="Sam"
            )
            is None
        )

    async def test_a_missing_rewrite_is_rejected_rather_than_written(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.rewrite.return_value = None

        assert (
            await consolidation._rewrite_within_cap(
                USER, MemoryDocType.USER_MD, "previous", ["## facts"], user_name="Sam"
            )
            is None
        )

    async def test_a_failed_rewrite_is_reported_on_the_wide_event(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.rewrite.return_value = None

        async with captured_wide_event() as event:
            await consolidation._rewrite_within_cap(
                USER, MemoryDocType.PEOPLE_MD, "previous", ["## facts"], user_name="Sam"
            )

        assert event["warnings"] == [
            {
                "msg": "memory_consolidation_doc_failed",
                "user_id": USER,
                "doc_type": "people_md",
                "error_type": "llm_returned_empty",
            }
        ]


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

    async def test_the_check_is_given_the_document_and_the_owner(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.verify.return_value = VerifiedDocument(content="# About", struck=[])

        await consolidation._strike_unsupported(
            USER, MemoryDocType.USER_MD, "# About\n- a line", [make_row("sam is vegetarian")]
        )

        call = boundaries.verify.await_args
        assert call.args == ("# About\n- a line", ["sam is vegetarian"])
        assert call.kwargs == {"user_id": USER}

    async def test_a_failed_check_keeps_the_unverified_document(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.verify.return_value = None

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.update_document.await_args.args[2] == "# About\n- something"

    async def test_a_failed_check_is_reported_on_the_wide_event(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.verify.return_value = None

        async with captured_wide_event() as event:
            await consolidation._strike_unsupported(
                USER, MemoryDocType.MEMORY_MD, "# About", [make_row()]
            )

        assert event["warnings"] == [
            {
                "msg": "memory_consolidation_verification_failed",
                "user_id": USER,
                "doc_type": "memory_md",
                "error_type": "llm_returned_empty",
            }
        ]

    async def test_struck_lines_are_reported_on_the_wide_event(self, boundaries: MagicMock) -> None:
        boundaries.verify.return_value = VerifiedDocument(
            content="# About", struck=["- a lie", "- another lie"]
        )

        async with captured_wide_event() as event:
            await consolidation._strike_unsupported(
                USER, MemoryDocType.PEOPLE_MD, "# About\n- a lie\n- another lie", [make_row()]
            )

        assert event["warnings"] == [
            {
                "msg": "memory_consolidation_struck_unsupported",
                "user_id": USER,
                "doc_type": "people_md",
                "error_type": "unsupported_document_lines",
                "struck_count": 2,
            }
        ]

    async def test_a_document_with_no_source_facts_skips_the_check(
        self, boundaries: MagicMock
    ) -> None:
        kept = await consolidation._strike_unsupported(USER, MemoryDocType.USER_MD, "# About", [])

        assert kept == "# About"
        boundaries.verify.assert_not_awaited()


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

    async def test_the_agenda_does_not_stop_the_documents_after_it(
        self, boundaries: MagicMock
    ) -> None:
        rewritten = await consolidate(USER, [MemoryDocType.AGENDA_MD, MemoryDocType.USER_MD])

        assert rewritten == [MemoryDocType.USER_MD]

    async def test_no_doc_types_rewrites_every_llm_written_document(
        self, boundaries: MagicMock
    ) -> None:
        rewritten = await consolidate(USER)

        assert rewritten == [
            MemoryDocType.USER_MD,
            MemoryDocType.MEMORY_MD,
            MemoryDocType.PEOPLE_MD,
        ]

    async def test_user_md_is_written_from_the_whole_fact_corpus(
        self, boundaries: MagicMock
    ) -> None:
        # user.md is the general-life document: every folder feeds it, so it is
        # the one document read without a category filter.
        await consolidate(USER, [MemoryDocType.USER_MD])

        call = boundaries.get_facts.await_args
        assert call.args == (USER,)
        assert call.kwargs == {
            "category_prefixes": None,
            "shelf_life": MemoryShelfLife.DURABLE.value,
            "limit": CONSOLIDATION_FACTS_LIMIT,
        }

    async def test_a_scoped_document_reads_only_the_folders_that_feed_it(
        self, boundaries: MagicMock
    ) -> None:
        await consolidate(USER, [MemoryDocType.MEMORY_MD])

        assert boundaries.get_facts.await_args.kwargs["category_prefixes"] == [
            "preferences",
            "food-preferences",
            "communication",
            "conventions",
        ]

    async def test_the_entity_register_is_appended_for_people_md(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.get_entities.return_value = [SimpleNamespace(name="Khyati Sheth")]

        await consolidate(USER, [MemoryDocType.PEOPLE_MD])

        assert boundaries.get_entities.await_args.args == (USER, MemoryEntityType.PERSON.value)
        assert (
            "## Known people (entity register)\n- Khyati Sheth"
            in boundaries.rewrite.await_args.args[1]
        )

    async def test_the_facts_corpus_reaches_the_prompt(self, boundaries: MagicMock) -> None:
        row = make_row("sam is vegetarian")
        boundaries.get_facts.return_value = [row]

        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.rewrite.await_args.args[1].endswith(
            "## Every fact this document is written from\n"
            f"- sam is vegetarian (stored {row.created_at:%Y-%m-%d})"
        )

    async def test_the_owner_is_named_in_the_prompt_the_model_receives(
        self, boundaries: MagicMock
    ) -> None:
        # people.md is the document that has to tell the user apart from the
        # people in it, so its prompt is the one carrying the owner's name.
        await consolidate(USER, [MemoryDocType.PEOPLE_MD])

        system_prompt = boundaries.rewrite.await_args.args[0]
        assert system_prompt == consolidation._system_prompt(MemoryDocType.PEOPLE_MD, "Sam")
        assert "Sam" in system_prompt

    async def test_every_write_is_scoped_to_its_owner_and_document(
        self, boundaries: MagicMock
    ) -> None:
        await consolidate(USER, [MemoryDocType.USER_MD])

        assert boundaries.update_document.await_args.args == (
            USER,
            MemoryDocType.USER_MD,
            "# About\n- something",
        )
        assert boundaries.rewrite.await_args.kwargs == {"user_id": USER}
        assert boundaries.verify.await_args.kwargs == {"user_id": USER}


@pytest.mark.unit
class TestConsolidationOutcomes:
    async def test_a_rewritten_document_is_reported_as_rewritten(
        self, boundaries: MagicMock
    ) -> None:
        async with captured_wide_event() as event:
            await consolidate(USER, [MemoryDocType.USER_MD])

        assert event["memory"]["outcomes"] == {"user_md": "rewritten"}
        assert event["memory"]["success"] is True

    async def test_a_failed_rewrite_is_reported_as_failed(self, boundaries: MagicMock) -> None:
        boundaries.rewrite.return_value = None

        async with captured_wide_event() as event:
            await consolidate(USER, [MemoryDocType.USER_MD])

        assert event["memory"]["outcomes"] == {"user_md": "failed"}
        assert event["memory"]["success"] is False

    async def test_a_document_with_nothing_to_write_from_is_reported_as_skipped(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.get_facts.return_value = []

        async with captured_wide_event() as event:
            rewritten = await consolidate(USER, [MemoryDocType.USER_MD])

        assert rewritten == []
        assert event["memory"]["outcomes"] == {"user_md": "skipped"}
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

        call = boundaries.get_agenda.await_args
        assert call.args == (USER,)
        assert call.kwargs == {"limit": AGENDA_INJECTED_ITEM_CAP}

    async def test_the_page_is_one_heading_and_one_line_per_row(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.get_agenda.return_value = [
            make_row("ship the billing migration"),
            make_row("file the tax return by March 3"),
        ]

        await render_agenda_document(USER)

        assert boundaries.update_document.await_args.args == (
            USER,
            MemoryDocType.AGENDA_MD,
            "# Current agenda\n- ship the billing migration\n- file the tax return by March 3",
        )

    async def test_an_empty_agenda_still_writes_a_page(self, boundaries: MagicMock) -> None:
        # A user who closed their last loop must end up with an empty agenda,
        # not the previous version left standing.
        await render_agenda_document(USER)

        content = boundaries.update_document.await_args.args[2]
        assert content == "# Current agenda\n- (nothing open)"


@pytest.mark.unit
class TestInferDocTypes:
    @staticmethod
    def _fact(
        category_path: str, shelf_life: MemoryShelfLife = MemoryShelfLife.DURABLE
    ) -> ExtractedFact:
        return ExtractedFact(
            content="owes the user a draft",
            kind=MemoryKind.FACT,
            shelf_life=shelf_life,
            category_path=category_path,
            importance=0.5,
        )

    def test_an_agenda_fact_feeds_no_consolidated_document(self) -> None:
        assert (
            consolidation.infer_doc_types([self._fact(AGENDA_CATEGORY_PATH, MemoryShelfLife.TASK)])
            == set()
        )

    def test_a_task_never_reaches_a_document_even_from_a_mapped_folder(self) -> None:
        # A commitment is an agenda row, not a line in an always-injected page.
        assert consolidation.infer_doc_types([self._fact("work", MemoryShelfLife.TASK)]) == set()

    def test_a_durable_fact_feeds_the_documents_its_folder_maps_to(self) -> None:
        assert consolidation.infer_doc_types([self._fact("relationships")]) == {
            MemoryDocType.PEOPLE_MD,
            MemoryDocType.USER_MD,
        }

    def test_a_preference_feeds_memory_md_only(self) -> None:
        assert consolidation.infer_doc_types([self._fact("preferences")]) == {
            MemoryDocType.MEMORY_MD
        }

    def test_an_unmapped_folder_falls_back_to_user_md(self) -> None:
        assert consolidation.infer_doc_types([self._fact("hobbies/climbing")]) == {
            MemoryDocType.USER_MD
        }

    def test_only_the_top_folder_decides(self) -> None:
        assert consolidation.infer_doc_types([self._fact("preferences/food/spice")]) == {
            MemoryDocType.MEMORY_MD
        }


@pytest.mark.unit
class TestFormatInputs:
    def test_the_previous_version_is_labelled_as_outranked_by_the_facts(self) -> None:
        assert consolidation._format_inputs("prev", ["## A", "## B"]) == (
            "## Previous version of the document (a draft — the facts below outrank it)\n"
            "prev\n\n## A\n\n## B"
        )

    def test_a_first_rewrite_says_so_rather_than_leaving_a_blank(self) -> None:
        assert consolidation._format_inputs("   ", []) == (
            "## Previous version of the document (a draft — the facts below outrank it)\n"
            "(no previous version)\n\n(no facts)"
        )
