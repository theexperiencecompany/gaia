"""Contract tests for LLMCallsRepository — the ``llm_calls`` ledger.

Real Mongo, because the two things that matter here are storage facts, not
Python facts: what actually lands in the document (a stored ``null`` reads back
identically to an absent field, so only Mongo can show which one we wrote), and
that a call with no user is still a row rather than a dropped write. This is the
collection that replaces log-scraping — a field that silently fails to persist
is a question nobody can answer three months later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.llm_calls import LLMCallDocument, LLMCallsRepository

CONVERSATION = "8f2a1c4e-0b3d-4a71-9c62-5d8e1f0a7b34"


@pytest.fixture
def repo(raw_collection) -> LLMCallsRepository:
    # Depends on ``raw_collection`` so the repository's collection accessor is
    # pointed at this test's throwaway collection.
    return LLMCallsRepository()


def _doc(**overrides: object) -> LLMCallDocument:
    fields: dict[str, object] = {
        "created_at": datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        "agent_name": "comms_agent",
        "background": False,
        "charge_to_budget": True,
        "model_requested": "deepseek/deepseek-v4-flash",
        "cost_source": "table",
    }
    fields.update(overrides)
    return LLMCallDocument.model_validate(fields)


class TestCreate:
    async def test_one_call_becomes_one_document_with_every_field_stored(
        self, repo, raw_collection
    ):
        await repo.create(
            _doc(
                user_id="u1",
                model_served="deepseek/deepseek-v4",
                provider="fireworks",
                input_tokens=1200,
                cached_tokens=800,
                output_tokens=90,
                reasoning_tokens=40,
                cost_usd=0.0037,
                cost_source="provider",
                generation_id="gen-abc123",
                conversation_id=CONVERSATION,
                lane_thread=f"executor_{CONVERSATION}",
                root_request_id="req-1",
                workflow_id="wf-1",
                workflow_execution_id="exec_wf-1_ab12cd34",
                job_id="job-9",
                task_name="run_workflow",
                duration_ms=1843.5,
            )
        )

        assert await raw_collection.count_documents({}) == 1
        raw = await raw_collection.find_one({})
        assert raw is not None
        assert raw["user_id"] == "u1"
        assert raw["model_requested"] == "deepseek/deepseek-v4-flash"
        assert raw["model_served"] == "deepseek/deepseek-v4"
        assert raw["provider"] == "fireworks"
        assert raw["input_tokens"] == 1200
        assert raw["cached_tokens"] == 800
        assert raw["output_tokens"] == 90
        assert raw["reasoning_tokens"] == 40
        assert raw["cost_usd"] == pytest.approx(0.0037)
        assert raw["cost_source"] == "provider"
        assert raw["generation_id"] == "gen-abc123"
        assert raw["conversation_id"] == CONVERSATION
        assert raw["lane_thread"] == f"executor_{CONVERSATION}"
        assert raw["root_request_id"] == "req-1"
        assert raw["workflow_id"] == "wf-1"
        assert raw["workflow_execution_id"] == "exec_wf-1_ab12cd34"
        assert raw["job_id"] == "job-9"
        assert raw["task_name"] == "run_workflow"
        assert raw["duration_ms"] == pytest.approx(1843.5)

    async def test_a_system_lane_call_with_no_user_is_still_recorded(self, repo, raw_collection):
        """``user_id`` is genuinely absent on system lanes. Dropping the write
        would leave that spend out of the ledger entirely."""
        await repo.create(_doc(agent_name="memory_consolidation", background=True))

        assert await raw_collection.count_documents({}) == 1
        raw = await raw_collection.find_one({})
        assert raw.get("user_id") is None
        assert raw["background"] is True

    async def test_unknown_identifiers_are_absent_rather_than_stored_as_null(
        self, repo, raw_collection
    ):
        """The base writes with ``exclude_none``, so an unreachable id leaves no
        key at all — which is what makes the sparse ``workflow_execution_id``
        index cover only the calls that really ran inside a workflow."""
        await repo.create(_doc())

        raw = await raw_collection.find_one({})
        assert "workflow_execution_id" not in raw
        assert "conversation_id" not in raw
        assert "job_id" not in raw
        assert "duration_ms" not in raw

    async def test_the_stored_document_carries_no_prompt_or_completion_text(
        self, repo, raw_collection
    ):
        """The ledger's hard invariant, checked on what Mongo actually holds."""
        await repo.create(
            _doc(user_id="u1", conversation_id=CONVERSATION, generation_id="gen-abc123")
        )

        raw = await raw_collection.find_one({})
        assert not any(
            isinstance(value, str) and " " in value for key, value in raw.items() if key != "_id"
        )

    async def test_every_call_is_its_own_row_never_an_upsert(self, repo, raw_collection):
        """Unlike ``usage_daily``, this collection does not roll up: two calls in
        one conversation are two rows, or the per-call ledger is not one."""
        await repo.create(_doc(user_id="u1", conversation_id=CONVERSATION, cost_usd=0.01))
        await repo.create(_doc(user_id="u1", conversation_id=CONVERSATION, cost_usd=0.02))

        assert await raw_collection.count_documents({"conversation_id": CONVERSATION}) == 2

    async def test_the_creation_time_the_caller_stamped_is_the_one_stored(
        self, repo, raw_collection
    ):
        """``created_at`` is both the TTL key and the time axis of every ledger
        query, so it has to be the moment the call was metered."""
        metered_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

        await repo.create(_doc(created_at=metered_at, user_id="u1"))

        raw = await raw_collection.find_one({})
        assert raw["created_at"].replace(tzinfo=UTC) == metered_at


class TestRead:
    async def test_a_stored_row_reads_back_as_the_same_document(self, repo, raw_collection):
        created = await repo.create(
            _doc(user_id="u1", conversation_id=CONVERSATION, cost_usd=0.0037)
        )

        fetched = await repo.get(created.id)

        assert fetched is not None
        assert fetched.model_dump(exclude={"id"}) == created.model_dump(exclude={"id"})


class TestBackfillIdempotency:
    """``--apply`` must be safe to re-run.

    The backfill takes long enough to be interrupted, and the natural response
    to an interrupted run is to run it again. If that duplicated history, every
    cost total the ledger feeds would silently double for the overlapping days.
    """

    async def test_re_running_the_same_batch_creates_nothing_the_second_time(
        self, repo, raw_collection
    ):
        await raw_collection.create_index("backfill_key", unique=True, sparse=True)
        batch = [
            _doc(user_id="u1", cost_usd=0.01, backfilled=True, backfill_key="key-a"),
            _doc(user_id="u1", cost_usd=0.02, backfilled=True, backfill_key="key-b"),
        ]

        first = await repo.insert_backfilled(batch)
        second = await repo.insert_backfilled(batch)

        assert (first, second) == (2, 0)
        assert await raw_collection.count_documents({}) == 2

    async def test_a_partial_re_run_fills_only_the_gap(self, repo, raw_collection):
        """The interrupted-run case: some rows landed, the rest did not. The
        second pass must add exactly what is missing."""
        await raw_collection.create_index("backfill_key", unique=True, sparse=True)
        await repo.insert_backfilled([_doc(user_id="u1", backfilled=True, backfill_key="key-a")])

        created = await repo.insert_backfilled(
            [
                _doc(user_id="u1", backfilled=True, backfill_key="key-a"),
                _doc(user_id="u1", backfilled=True, backfill_key="key-b"),
            ]
        )

        assert created == 1
        assert await raw_collection.count_documents({}) == 2

    async def test_the_stored_backfilled_row_is_marked_as_such(self, repo, raw_collection):
        """Backfilled rows carry only the context the log line held, so an
        analysis that needs first-party precision has to be able to exclude
        them."""
        await raw_collection.create_index("backfill_key", unique=True, sparse=True)

        await repo.insert_backfilled([_doc(user_id="u1", backfilled=True, backfill_key="key-a")])

        raw = await raw_collection.find_one({})
        assert raw["backfilled"] is True
        assert raw["backfill_key"] == "key-a"

    async def test_an_empty_batch_is_not_a_write(self, repo):
        assert await repo.insert_backfilled([]) == 0
