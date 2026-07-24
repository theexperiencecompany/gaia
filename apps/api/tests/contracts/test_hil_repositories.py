"""Contract tests for the HIL repositories (approval records + tool-risk cache).

The behaviors that must survive any backend: once-only record creation under the
deterministic ``approval_id`` (a resume replay's duplicate insert is a no-op that
never resets a decided record), the one-time ``pending -> decided`` transition,
and the sweep/join finders' exact filters.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.hil import HIL_UNRESUMED_SWEEP_STATUSES
from app.db.repositories.hil import HilApprovalRepository, HilToolRiskRepository
from app.models.hil_models import HILApprovalRecord, HILApprovalUpdate, HILToolRiskRecord


def _record(approval_id: str, **overrides: object) -> HILApprovalRecord:
    data: dict[str, object] = {
        "approval_id": approval_id,
        "user_id": "u1",
        "conversation_id": "conv-1",
        "stream_id": "stream-1",
        "tool_name": "send_email",
        "tool_call_id": f"tc-{approval_id}",
        "expires_at": datetime.now(UTC) + timedelta(hours=6),
    }
    data.update(overrides)
    return HILApprovalRecord.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> HilApprovalRepository:
    return HilApprovalRepository()


@pytest.fixture
def risk_repo(raw_collection) -> HilToolRiskRepository:
    return HilToolRiskRepository()


class TestHilApprovalRepository:
    async def test_create_if_absent_is_once_only(self, repo):
        assert await repo.create_if_absent(_record("a1")) is True
        assert await repo.create_if_absent(_record("a1")) is False, (
            "a resume replay's duplicate insert must be a no-op"
        )

    async def test_a_replay_never_resets_a_decided_record(self, repo):
        await repo.create_if_absent(_record("a1"))
        await repo.mark_decided("a1", "approved", feedback=None, scope="once", decided_by="u1")

        await repo.create_if_absent(_record("a1"))

        got = await repo.get("a1")
        assert got is not None and got.status == "approved"

    async def test_mark_decided_transitions_exactly_once(self, repo):
        await repo.create_if_absent(_record("a1"))

        first = await repo.mark_decided(
            "a1", "approved", feedback=None, scope="once", decided_by="u1"
        )
        second = await repo.mark_decided(
            "a1", "denied", feedback="no", scope="once", decided_by="u1"
        )

        assert first is True
        assert second is False, "a racing duplicate decision must not double-resolve"
        got = await repo.get("a1")
        assert got is not None and got.status == "approved" and got.decided_at is not None

    async def test_mark_decided_on_a_missing_record_is_false(self, repo):
        assert (
            await repo.mark_decided(
                "ghost", "approved", feedback=None, scope="once", decided_by=None
            )
            is False
        )

    async def test_stamps_land_via_the_update_model(self, repo):
        await repo.create_if_absent(_record("a1"))

        await repo.update("a1", HILApprovalUpdate(resume_item={"task": "t"}))
        await repo.update("a1", HILApprovalUpdate(resumed_at=datetime.now(UTC)))

        got = await repo.get("a1")
        assert got is not None
        assert got.resume_item == {"task": "t"}
        assert got.resumed_at is not None

    async def test_parked_subagent_finder_excludes_collected(self, repo):
        await repo.create_if_absent(_record("plain"))
        await repo.create_if_absent(_record("parked"))
        await repo.update(
            "parked", HILApprovalUpdate(subagent_thread_id="t-1", subagent_agent_name="gmail")
        )
        await repo.create_if_absent(_record("collected"))
        await repo.update(
            "collected",
            HILApprovalUpdate(
                subagent_thread_id="t-2",
                subagent_agent_name="slack",
                subagent_collected_at=datetime.now(UTC),
            ),
        )

        parked = await repo.list_parked_subagents_for_conversation("conv-1")

        assert [r.approval_id for r in parked] == ["parked"]

    async def test_expired_pending_finder_ignores_live_and_decided(self, repo):
        past = datetime.now(UTC) - timedelta(minutes=1)
        await repo.create_if_absent(_record("expired", expires_at=past))
        await repo.create_if_absent(_record("live"))
        await repo.create_if_absent(_record("decided", expires_at=past))
        await repo.mark_decided("decided", "approved", feedback=None, scope="once", decided_by=None)

        expired = await repo.list_expired_pending()

        assert [r.approval_id for r in expired] == ["expired"]

    async def test_decided_unresumed_finder_matches_only_crashed_dispatches(self, repo):
        for approval_id in ("crashed", "dispatched", "fresh", "contextless"):
            await repo.create_if_absent(_record(approval_id))
            await repo.mark_decided(
                approval_id, "approved", feedback=None, scope="once", decided_by=None
            )
        # Backdate every decision past the grace window, then differentiate.
        for approval_id in ("crashed", "dispatched", "contextless"):
            await repo._apply_raw_update(
                {"_id": approval_id},
                {"$set": {"decided_at": datetime.now(UTC) - timedelta(minutes=10)}},
                scope="global",
                return_document=False,
            )
        await repo.update("crashed", HILApprovalUpdate(resume_item={"task": "t"}))
        await repo.update(
            "dispatched",
            HILApprovalUpdate(resume_item={"task": "t"}, resumed_at=datetime.now(UTC)),
        )

        stale = await repo.list_decided_unresumed(["approved", "denied"], grace_seconds=120)

        assert [r.approval_id for r in stale] == ["crashed"]

    async def test_pending_for_conversation_is_scoped_and_oldest_first(self, repo):
        await repo.create_if_absent(
            _record("old", created_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await repo.create_if_absent(_record("new"))
        await repo.create_if_absent(_record("other", conversation_id="conv-2"))
        await repo.create_if_absent(_record("done"))
        await repo.mark_decided("done", "denied", feedback=None, scope="once", decided_by=None)

        pending = await repo.list_pending_for_conversation("conv-1")

        assert [r.approval_id for r in pending] == ["old", "new"]


class TestAutoApprovalRecords:
    """An auto-approved action already ran: its record is a receipt, never a request."""

    async def _auto_record(self, repo, approval_id: str = "auto-1") -> None:
        now = datetime.now(UTC)
        await repo.create_if_absent(
            _record(
                approval_id,
                status="auto_approved",
                auto_reason="you said send the deck to bob",
                decided_at=now,
                expires_at=now,
            )
        )

    async def test_it_is_born_decided_so_no_decision_can_resolve_it(self, repo):
        await self._auto_record(repo)

        assert (
            await repo.mark_decided(
                "auto-1", "approved", feedback=None, scope="once", decided_by="u1"
            )
            is False
        )
        got = await repo.get("auto-1")
        assert got is not None
        assert got.status == "auto_approved"
        assert got.auto_reason == "you said send the deck to bob"

    async def test_the_timeout_sweep_never_picks_it_up(self, repo):
        # expires_at is already in the past, but only *pending* records time out.
        await self._auto_record(repo)

        assert await repo.list_expired_pending() == []

    async def test_the_crashed_resume_sweep_ignores_it(self, repo):
        # auto_approved never called interrupt(), so it has no run to re-dispatch —
        # re-dispatching would replay an action that already happened. The service's
        # real status list is what must exclude it.
        await self._auto_record(repo)
        await repo.update("auto-1", HILApprovalUpdate(resume_item={"task": "t"}))
        await repo._apply_raw_update(
            {"_id": "auto-1"},
            {"$set": {"decided_at": datetime.now(UTC) - timedelta(minutes=10)}},
            scope="global",
            return_document=False,
        )

        stale = await repo.list_decided_unresumed(
            list(HIL_UNRESUMED_SWEEP_STATUSES), grace_seconds=120
        )

        assert stale == []
        assert "auto_approved" not in HIL_UNRESUMED_SWEEP_STATUSES
        assert "pending" not in HIL_UNRESUMED_SWEEP_STATUSES

    async def test_it_never_appears_as_a_pending_approval(self, repo):
        await self._auto_record(repo)

        assert await repo.list_pending_for_conversation("conv-1") == []


class TestHilToolRiskRepository:
    async def test_upsert_then_find_roundtrip(self, risk_repo):
        await risk_repo.upsert_classification(
            HILToolRiskRecord(tool_name="t", description_hash="h1", is_destructive=True)
        )

        got = await risk_repo.find_classification("t", "h1")

        assert got is not None and got.is_destructive is True
        assert await risk_repo.find_classification("t", "other-hash") is None

    async def test_upsert_overwrites_the_same_key_in_place(self, risk_repo):
        await risk_repo.upsert_classification(
            HILToolRiskRecord(tool_name="t", description_hash="h1", is_destructive=True)
        )
        await risk_repo.upsert_classification(
            HILToolRiskRecord(tool_name="t", description_hash="h1", is_destructive=False)
        )

        got = await risk_repo.find_classification("t", "h1")

        assert got is not None and got.is_destructive is False
