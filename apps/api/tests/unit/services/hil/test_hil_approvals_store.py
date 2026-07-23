"""Attacks on the approval store (app/services/hil/approvals_store.py).

This is the decision source of truth, and two of its guarantees are carried entirely by
the shape of a single Mongo query document — which makes them easy to break in a way no
other test would notice:

* **Exactly once.** ``mark_decided`` filters on ``status: "pending"``. Drop that one key
  and a late click, a racing bot callback, or the sweep firing against an approval the
  user just answered all overwrite the decision and resume the run a second time.
* **Idempotent creation.** The pending record is written with ``$setOnInsert``. Make it a
  ``$set`` and every resume replay resets a decided record back to pending.

The rest is query-shape too: which records the sweep picks up, and which the join collects.
The collection is mocked, so these assert on the documents the module actually builds.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.services.hil.approvals_store import (
    get_approval,
    list_decided_unresumed,
    list_expired_pending,
    list_parked_subagents_for_conversation,
    list_pending_for_conversation,
    mark_decided,
    mark_subagent_collected,
    record_auto_approval,
    upsert_pending_approval,
)

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_record

MODULE = "app.services.hil.approvals_store"


class FakeCursor:
    """Motor's find() result: async-iterable, and chainable through .sort()."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def sort(self, *_args: Any, **_kwargs: Any) -> "FakeCursor":
        return self

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for doc in self.docs:
                yield doc

        return gen()


@pytest.fixture
def collection():
    with patch(f"{MODULE}.hil_approvals_collection") as coll:
        coll.update_one = AsyncMock(return_value=MagicMock(upserted_id=None, modified_count=0))
        coll.find_one = AsyncMock(return_value=None)
        coll.find = MagicMock(return_value=FakeCursor([]))
        yield coll


def filter_of(collection: MagicMock) -> dict[str, Any]:
    return collection.update_one.await_args.args[0]


def update_of(collection: MagicMock) -> dict[str, Any]:
    return collection.update_one.await_args.args[1]


def find_filter(collection: MagicMock) -> dict[str, Any]:
    return collection.find.call_args.args[0]


async def create_pending(collection: MagicMock, **overrides: Any) -> bool:
    kwargs: dict[str, Any] = {
        "approval_id": "appr-1",
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "stream_id": STREAM_ID,
        "tool_name": "send_email",
        "tool_call_id": "call-1",
        "args": {"to": "bob@example.com"},
        "summary": "Send email",
        "integration_name": "Gmail",
    }
    return await upsert_pending_approval(**{**kwargs, **overrides})


class TestIdempotentCreation:
    async def test_the_pending_record_is_written_insert_only(self, collection: MagicMock) -> None:
        # The gate's pre-interrupt code re-runs from the top on every resume replay. A
        # `$set` here would reset an already-decided record back to pending and re-ask.
        await create_pending(collection)

        update = update_of(collection)
        assert "$setOnInsert" in update
        assert "$set" not in update

    async def test_creation_is_reported_only_when_the_record_was_actually_new(
        self, collection: MagicMock
    ) -> None:
        # This return value is what gates publishing the card. Reporting True on a replay
        # would show the user a second card for an approval they already have.
        collection.update_one.return_value = MagicMock(upserted_id=None)
        assert await create_pending(collection) is False

        collection.update_one.return_value = MagicMock(upserted_id="appr-1")
        assert await create_pending(collection) is True

    async def test_the_record_starts_pending_with_a_future_expiry(
        self, collection: MagicMock
    ) -> None:
        before = datetime.now(UTC)
        await create_pending(collection)

        doc = update_of(collection)["$setOnInsert"]
        assert doc["status"] == "pending"
        assert doc["decided_at"] is None
        expected = before + timedelta(seconds=HIL_APPROVAL_TIMEOUT_SECONDS)
        assert doc["expires_at"] >= expected - timedelta(seconds=5)

    async def test_the_id_is_the_mongo_key_so_a_replay_collides_by_construction(
        self, collection: MagicMock
    ) -> None:
        await create_pending(collection, approval_id="appr-xyz")

        assert filter_of(collection) == {"_id": "appr-xyz"}
        assert update_of(collection)["$setOnInsert"]["_id"] == "appr-xyz"


class TestAutoApprovalRecord:
    async def test_it_is_written_already_decided_so_nothing_can_resolve_it(
        self, collection: MagicMock
    ) -> None:
        # An auto-approved action already ran. Written as `pending` it would show the user
        # an approve/deny card for something that has already happened.
        await record_auto_approval(
            approval_id="appr-1",
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            stream_id=STREAM_ID,
            tool_name="send_email",
            tool_call_id="call-1",
            args={},
            summary="Send email",
            integration_name=None,
            reason="you said send the deck to bob",
        )

        doc = update_of(collection)["$setOnInsert"]
        assert doc["status"] == "auto_approved"
        assert doc["decided_at"] is not None
        assert doc["auto_reason"] == "you said send the deck to bob"

    async def test_it_expires_immediately_so_the_timeout_sweep_never_picks_it_up(
        self, collection: MagicMock
    ) -> None:
        await record_auto_approval(
            approval_id="appr-1",
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            stream_id=STREAM_ID,
            tool_name="send_email",
            tool_call_id="call-1",
            args={},
            summary="Send email",
            integration_name=None,
            reason="because",
        )

        doc = update_of(collection)["$setOnInsert"]
        assert doc["expires_at"] <= datetime.now(UTC)


class TestExactlyOnceTransition:
    async def test_only_a_pending_record_can_be_decided(self, collection: MagicMock) -> None:
        # THE invariant. Without `status: "pending"` in the filter, a second decision
        # overwrites the first and resumes the paused run twice.
        await mark_decided("appr-1", "approved", feedback=None, scope="once", decided_by=USER_ID)

        assert filter_of(collection) == {"_id": "appr-1", "status": "pending"}

    async def test_the_transition_is_reported_only_when_this_call_performed_it(
        self, collection: MagicMock
    ) -> None:
        collection.update_one.return_value = MagicMock(modified_count=1)
        assert (
            await mark_decided("a", "approved", feedback=None, scope="once", decided_by=USER_ID)
            is True
        )

        collection.update_one.return_value = MagicMock(modified_count=0)
        assert (
            await mark_decided("a", "approved", feedback=None, scope="once", decided_by=USER_ID)
            is False
        )

    async def test_a_matched_but_unmodified_document_is_not_a_transition(
        self, collection: MagicMock
    ) -> None:
        # matched_count would be 1 for a no-op write. Keying off it instead of
        # modified_count would let a duplicate decision claim it won the race.
        collection.update_one.return_value = MagicMock(matched_count=1, modified_count=0)

        assert (
            await mark_decided("a", "denied", feedback=None, scope="once", decided_by=USER_ID)
            is False
        )

    async def test_the_decision_and_its_author_are_recorded(self, collection: MagicMock) -> None:
        await mark_decided(
            "appr-1", "denied", feedback="wrong person", scope="once", decided_by=USER_ID
        )

        written = update_of(collection)["$set"]
        assert written["status"] == "denied"
        assert written["feedback"] == "wrong person"
        assert written["decided_by"] == USER_ID
        assert written["decided_at"] is not None


class TestSweepQueries:
    async def test_the_timeout_pass_takes_only_pending_records_past_expiry(
        self, collection: MagicMock
    ) -> None:
        await list_expired_pending()

        query = find_filter(collection)
        assert query["status"] == "pending"
        assert "$lt" in query["expires_at"]

    async def test_the_crashed_resume_pass_ignores_records_that_never_paused(
        self, collection: MagicMock
    ) -> None:
        # `auto_approved` never called interrupt(), so it has no run to re-dispatch.
        # Re-dispatching it would replay an action that already happened.
        await list_decided_unresumed(120)

        statuses = find_filter(collection)["status"]["$in"]
        assert "auto_approved" not in statuses
        assert "pending" not in statuses
        assert set(statuses) == {"approved", "denied", "timeout", "abandoned"}

    async def test_the_crashed_resume_pass_requires_something_to_re_dispatch_from(
        self, collection: MagicMock
    ) -> None:
        await list_decided_unresumed(120)

        query = find_filter(collection)
        assert query["resume_item"] == {"$ne": None}
        assert query["resumed_at"] is None

    async def test_the_grace_period_is_applied_as_a_cutoff_in_the_past(
        self, collection: MagicMock
    ) -> None:
        # Without the grace window the sweep races a resume that is mid-dispatch and
        # starts a second LangGraph run on the same thread.
        await list_decided_unresumed(120)

        cutoff = find_filter(collection)["decided_at"]["$lt"]
        assert cutoff <= datetime.now(UTC) - timedelta(seconds=119)


class TestConversationQueries:
    async def test_pending_lookup_is_scoped_to_the_conversation(
        self, collection: MagicMock
    ) -> None:
        await list_pending_for_conversation(CONVERSATION_ID)

        assert find_filter(collection) == {
            "conversation_id": CONVERSATION_ID,
            "status": "pending",
        }

    async def test_the_join_selects_on_collection_not_on_executor_re_dispatch(
        self, collection: MagicMock
    ) -> None:
        # `resumed_at` is stamped when the FIRST decision wakes the executor. Filtering on
        # it would drop every other member of a batch pause before the join collected them.
        await list_parked_subagents_for_conversation(CONVERSATION_ID)

        query = find_filter(collection)
        assert query["subagent_collected_at"] is None
        assert "resumed_at" not in query
        assert query["subagent_thread_id"] == {"$ne": None}

    async def test_the_join_ignores_approvals_no_subagent_parked_on(
        self, collection: MagicMock
    ) -> None:
        await list_parked_subagents_for_conversation(CONVERSATION_ID)

        assert find_filter(collection)["subagent_thread_id"] == {"$ne": None}

    async def test_records_are_hydrated_into_the_real_model(self, collection: MagicMock) -> None:
        doc = make_record(approval_id="appr-7").model_dump()
        doc["_id"] = "appr-7"
        collection.find.return_value = FakeCursor([doc])

        records = await list_pending_for_conversation(CONVERSATION_ID)

        assert len(records) == 1
        assert records[0].approval_id == "appr-7"
        assert records[0].tool_name == "send_email"


class TestSingleRecordLookup:
    async def test_a_missing_approval_is_none_rather_than_an_error(
        self, collection: MagicMock
    ) -> None:
        collection.find_one.return_value = None

        assert await get_approval("nope") is None

    async def test_a_decided_record_round_trips_with_its_decision_intact(
        self, collection: MagicMock
    ) -> None:
        # Everything the resume path acts on is read off a hydrated record. A field lost
        # or mis-mapped here silently changes the decision that gets replayed.
        doc = make_record(
            status="denied",
            feedback="wrong recipient",
            decided_by=USER_ID,
            scope="always_tool",
            subagent_thread_id="gmail_executor_conv-1",
        ).model_dump()
        doc["_id"] = "appr-1"
        collection.find_one.return_value = doc

        record = await get_approval("appr-1")

        assert record is not None
        assert record.status == "denied"
        assert record.feedback == "wrong recipient"
        assert record.decided_by == USER_ID
        assert record.scope == "always_tool"
        assert record.subagent_thread_id == "gmail_executor_conv-1"
        assert record.resume_item == {"run": "item"}

    async def test_the_lookup_is_keyed_on_the_approval_id(self, collection: MagicMock) -> None:
        await get_approval("appr-9")

        assert collection.find_one.await_args.args[0] == {"_id": "appr-9"}


class TestCollectionStamp:
    async def test_collecting_a_subagent_stamps_a_time_not_a_flag(
        self, collection: MagicMock
    ) -> None:
        # The join filters on `subagent_collected_at is None`, so this must write a value
        # that is not None — a falsey stamp would leave the record in the work list forever.
        await mark_subagent_collected("appr-1")

        stamped = update_of(collection)["$set"]["subagent_collected_at"]
        assert stamped is not None
        assert isinstance(stamped, datetime)
