"""Hermetic unit tests for ApprovalLedgerRepository.

Real-Mongo proof belongs in the contracts tier; this tier pins the exact
filters and update documents handed to the driver — especially the CAS filter
(state == expected), which is the whole safety story, and the live-only
dedup scope (terminal fingerprints must re-register fresh).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.approval_ledger import (
    ApprovalLedgerRepository,
    approval_ledger_repository,
)
from app.models.hil_models import ApprovalProposal, LedgerState

_PROPOSAL = ApprovalProposal(
    conversation_id="c1", fingerprint="fp", tool_name="T", args={}, summary="s"
)


def _doc(
    state: str = "pending", approval_id: str = "ap_1", fingerprint: str = "fp"
) -> dict[str, Any]:
    return {
        "_id": "oid",
        "approval_id": approval_id,
        "conversation_id": "c1",
        "fingerprint": fingerprint,
        "tool_name": "T",
        "args": {},
        "summary": "s",
        "rationale": "",
        "preview": "",
        "owner_agent": "executor",
        "blocked_by": [],
        "state": state,
        "v": 0,
    }


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid"))
    mock.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock.find_one = AsyncMock(return_value=_doc())
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])
    mock.find = MagicMock(return_value=cursor)
    with patch("app.db.repositories.base.get_async_collection", return_value=mock):
        yield mock


@pytest.fixture
def repo() -> ApprovalLedgerRepository:
    return ApprovalLedgerRepository()


def _find_returns(collection: MagicMock, *pages: list[dict[str, Any]]) -> MagicMock:
    """Make each successive find() yield the next page; returns the shared cursor."""
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(side_effect=list(pages))
    collection.find = MagicMock(return_value=cursor)
    return cursor


_LIVE_STATES_IN = {"$in": ["approved", "pending"]}


@pytest.mark.unit
class TestRegister:
    async def test_inserts_pending_and_returns_new_id(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        ap_id = await repo.register(_PROPOSAL)

        assert re.fullmatch(r"ap_[0-9a-f]{12}", ap_id)
        inserted = collection.insert_one.await_args.args[0]
        assert inserted["state"] == "pending"
        assert inserted["approval_id"] == ap_id

    async def test_live_duplicate_returns_existing_id_without_insert(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[_doc(state="approved")])
        collection.find = MagicMock(return_value=cursor)

        ap_id = await repo.register(_PROPOSAL)

        assert ap_id == "ap_1"
        collection.insert_one.assert_not_awaited()
        assert collection.find.call_args.args[0] == {
            "fingerprint": "fp",
            "conversation_id": "c1",
            "state": _LIVE_STATES_IN,
        }

    async def test_lost_insert_race_returns_the_winners_id(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        _find_returns(collection, [], [_doc(approval_id="ap_winner")])
        collection.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))

        ap_id = await repo.register(_PROPOSAL)

        assert ap_id == "ap_winner"
        lookups = [c.args[0] for c in collection.find.call_args_list]
        assert [(f["fingerprint"], f["conversation_id"]) for f in lookups] == [
            ("fp", "c1"),
            ("fp", "c1"),
        ]

    async def test_lost_insert_race_with_no_live_winner_reraises(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        _find_returns(collection, [], [])
        collection.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))

        with pytest.raises(DuplicateKeyError):
            await repo.register(_PROPOSAL)

    async def test_terminal_fingerprint_registers_fresh(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[_doc(state="revoked")])
        collection.find = MagicMock(return_value=cursor)

        ap_id = await repo.register(_PROPOSAL)

        assert ap_id != "ap_1"
        collection.insert_one.assert_awaited_once()


@pytest.mark.unit
class TestTransition:
    async def test_matching_state_transitions_and_bumps_version(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        assert await repo.transition("ap_1", LedgerState.PENDING, LedgerState.APPROVED) is True

        flt, update = collection.update_one.await_args.args
        assert flt == {"approval_id": "ap_1", "state": "pending"}
        assert update["$set"] == {"state": "approved"}
        assert update["$inc"] == {"v": 1}

    async def test_mismatched_state_is_a_quiet_false(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        collection.update_one = AsyncMock(return_value=MagicMock(modified_count=0))

        assert await repo.transition("ap_1", LedgerState.PENDING, LedgerState.DENIED) is False

    async def test_decision_stamp_rides_in_the_same_write(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        assert (
            await repo.transition(
                "ap_1",
                LedgerState.PENDING,
                LedgerState.DENIED,
                decided_by="u1",
                feedback="nope",
            )
            is True
        )

        _, update = collection.update_one.await_args.args
        assert update["$set"]["state"] == "denied"
        assert update["$set"]["decided_by"] == "u1"
        assert update["$set"]["feedback"] == "nope"
        decided_at = update["$set"]["decided_at"]
        assert isinstance(decided_at, datetime)
        assert decided_at.tzinfo is UTC

    @pytest.mark.parametrize(
        "stamp", [{"decided_by": "u1"}, {"feedback": "nope"}], ids=["decider", "feedback"]
    )
    async def test_either_stamp_alone_still_records_decided_at(
        self, repo: ApprovalLedgerRepository, collection: MagicMock, stamp: dict[str, str]
    ) -> None:
        await repo.transition("ap_1", LedgerState.PENDING, LedgerState.DENIED, **stamp)

        _, update = collection.update_one.await_args.args
        assert update["$set"]["decided_at"].tzinfo is UTC


@pytest.mark.unit
class TestClaims:
    async def test_claim_resume_wins_only_an_unresumed_row(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        assert await repo.claim_resume("ap_1") is True

        flt, update = collection.update_one.await_args.args
        assert flt == {"approval_id": "ap_1", "owner_resumed": False}
        assert update == {"$set": {"owner_resumed": True}}

    async def test_claim_resume_loser_gets_false(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        collection.update_one = AsyncMock(return_value=MagicMock(modified_count=0))

        assert await repo.claim_resume("ap_1") is False

    async def test_claim_executing_moves_approved_to_executing_with_a_stamp(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        assert await repo.claim_executing("ap_1") is True

        flt, update = collection.update_one.await_args.args
        assert flt == {"approval_id": "ap_1", "state": "approved"}
        assert update["$set"]["state"] == "executing"
        assert update["$set"]["executing_started_at"].tzinfo is UTC
        assert update["$inc"] == {"v": 1}

    async def test_claim_executing_loser_gets_false(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        collection.update_one = AsyncMock(return_value=MagicMock(modified_count=0))

        assert await repo.claim_executing("ap_1") is False


@pytest.mark.unit
class TestReads:
    async def test_list_open_filters_live_and_sorts_oldest_first(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[_doc()])
        collection.find = MagicMock(return_value=cursor)

        docs = await repo.list_open("c1")

        flt = collection.find.call_args.args[0]
        assert flt["conversation_id"] == "c1"
        assert set(flt["state"]["$in"]) == {"pending", "approved"}
        cursor.sort.assert_called_once_with("created_at", 1)
        cursor.to_list.assert_awaited_once_with(length=200)
        assert len(docs) == 1 and docs[0].approval_id == "ap_1"

    async def test_find_live_queries_live_rows_newest_first(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = _find_returns(collection, [_doc(state="approved")])

        doc = await repo.find_live("fp", "c1")

        assert collection.find.call_args.args[0] == {
            "fingerprint": "fp",
            "conversation_id": "c1",
            "state": _LIVE_STATES_IN,
        }
        cursor.sort.assert_called_once_with("created_at", -1)
        cursor.to_list.assert_awaited_once_with(length=50)
        assert doc is not None and doc.approval_id == "ap_1"

    async def test_find_live_skips_a_terminal_row_and_returns_none(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        _find_returns(collection, [_doc(state="revoked")])

        assert await repo.find_live("fp", "c1") is None

    async def test_get_by_approval_id_reads_one_row_or_none(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        found = await repo.get_by_approval_id("ap_1")
        collection.find_one = AsyncMock(return_value=None)
        missing = await repo.get_by_approval_id("ap_2")

        assert found is not None and found.approval_id == "ap_1"
        assert missing is None
        assert collection.find_one.await_args.args[0] == {"approval_id": "ap_2"}

    async def test_list_stalled_executing_scopes_to_the_conversation_oldest_first(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = _find_returns(collection, [_doc(state="executing")])
        cutoff = datetime(2026, 1, 1, tzinfo=UTC)

        docs = await repo.list_stalled_executing(cutoff, conversation_id="c1")

        assert collection.find.call_args.args[0] == {
            "state": "executing",
            "executing_started_at": {"$lt": cutoff},
            "conversation_id": "c1",
        }
        cursor.sort.assert_called_once_with("executing_started_at", 1)
        cursor.to_list.assert_awaited_once_with(length=200)
        assert [d.state for d in docs] == [LedgerState.EXECUTING]

    async def test_list_stalled_executing_without_conversation_scans_all(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        _find_returns(collection, [])

        await repo.list_stalled_executing(datetime(2026, 1, 1, tzinfo=UTC))

        assert "conversation_id" not in collection.find.call_args.args[0]

    async def test_recent_tool_outcomes_reads_decided_rows_newest_first(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = _find_returns(collection, [_doc(state="approved")])
        expected_cutoff = datetime.now(UTC) - timedelta(days=7)

        docs = await repo.recent_tool_outcomes("u1", "T", limit=3, since_days=7)

        flt = collection.find.call_args.args[0]
        assert (flt["user_id"], flt["tool_name"]) == ("u1", "T")
        assert abs(flt["decided_at"]["$gte"] - expected_cutoff) < timedelta(seconds=5)
        cursor.sort.assert_called_once_with("decided_at", -1)
        cursor.to_list.assert_awaited_once_with(length=3)
        assert len(docs) == 1

    async def test_recent_tool_outcomes_defaults_to_ten_votes_over_thirty_days(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        cursor = _find_returns(collection, [])
        expected_cutoff = datetime.now(UTC) - timedelta(days=30)

        await repo.recent_tool_outcomes("u1", "T")

        cutoff = collection.find.call_args.args[0]["decided_at"]["$gte"]
        assert abs(cutoff - expected_cutoff) < timedelta(seconds=5)
        cursor.to_list.assert_awaited_once_with(length=10)

    async def test_find_latest_denied_queries_denied_newest_first(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        collection.find_one = AsyncMock(return_value=_doc(state="denied"))

        doc = await repo.find_latest_denied("fp", "c1")

        flt = collection.find_one.await_args.args[0]
        assert flt == {"fingerprint": "fp", "conversation_id": "c1", "state": "denied"}
        assert collection.find_one.await_args.kwargs == {"sort": [("created_at", -1)]}
        assert doc is not None and doc.state == LedgerState.DENIED

    async def test_singleton_exists(self) -> None:
        assert isinstance(approval_ledger_repository, ApprovalLedgerRepository)

    async def test_list_live_by_owners_batches_one_query(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        """List views read one page, not one row per todo."""
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[_doc()])
        collection.find = MagicMock(return_value=cursor)

        docs = await repo.list_live_by_owners("todo", ["todo-1", "todo-2"])

        flt = collection.find.call_args.args[0]
        assert flt["owner_run_type"] == "todo"
        assert flt["owner_id"] == {"$in": ["todo-1", "todo-2"]}
        assert set(flt["state"]["$in"]) == {"pending", "approved"}
        cursor.sort.assert_called_once_with("created_at", 1)
        cursor.to_list.assert_awaited_once_with(length=200)
        assert len(docs) == 1

    async def test_list_live_by_owners_empty_means_no_query(
        self, repo: ApprovalLedgerRepository, collection: MagicMock
    ) -> None:
        assert await repo.list_live_by_owners("todo", []) == []
        assert await repo.list_live_by_owners("", ["todo-1"]) == []
        collection.find.assert_not_called()
