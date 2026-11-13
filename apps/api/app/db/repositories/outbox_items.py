"""Repository for outbox items: one submitted report and where it stands on its way out.

Every transition is a single conditional write on the state the item must be in, so
of two workers moving one item only one wins; the loser sees it and stops.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Literal, NamedTuple

from pymongo.errors import DuplicateKeyError

from app.constants.outbox import ITEMS_COLLECTION
from app.constants.outbox_attention import HoldReason
from app.db.repositories.base import UserScopedRepository
from app.models.outbox_models import OutboxItemDocument, OutboxItemUpdate
from app.services.outbox.judge_models import ItemJudgement
from app.services.outbox.models import (
    UNSENT_STATES,
    ComposeMode,
    DropReason,
    ItemFailure,
    ItemHold,
    ItemState,
    OutboxReport,
    UrgencyClass,
)
from app.utils import clock

#: States in which an item has been, or is being, told: a newer report of its subject outranks it.
_TOLD_OR_TELLING_STATES = frozenset(
    {ItemState.COMPOSING, ItemState.SENDING, ItemState.SENT, *UNSENT_STATES}
)


def _judgement_fields(judgement: ItemJudgement | None) -> dict[str, object]:
    return {} if judgement is None else {"judgement": judgement.model_dump(mode="python")}


def _outcome_in(outcomes: Collection[str]) -> dict[str, object]:
    values = list(outcomes)
    return {
        "$or": [{"report.report.outcome": {"$in": values}}, {"report.outcome": {"$in": values}}]
    }


class InsertedItem(NamedTuple):
    """The stored item for a report, and whether this call is the one that stored it."""

    item: OutboxItemDocument
    created: bool


class OutboxItemsRepository(UserScopedRepository[OutboxItemDocument, OutboxItemUpdate]):
    """Persistence for outbox items, unique on (user_id, report_id)."""

    collection_name = ITEMS_COLLECTION
    document_model = OutboxItemDocument
    update_model = OutboxItemUpdate
    uses_object_id = True
    cache_policy = None

    async def insert_if_new(self, report: OutboxReport, *, expires_at: datetime) -> InsertedItem:
        """Store the report as a received item, or return the item an earlier submit stored."""
        now = clock.now()
        item = OutboxItemDocument(
            user_id=report.recipient,
            report_id=report.report_id,
            report=report,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        try:
            await self._raw_collection().insert_one(
                item.model_dump(exclude={"id"}, exclude_none=True)
            )
        except DuplicateKeyError:
            existing = await self.get_by_report(report.recipient, report.report_id)
            if existing is None:
                raise
            return InsertedItem(existing, created=False)
        stored = await self.get_by_report(report.recipient, report.report_id)
        if stored is None:
            raise RuntimeError(f"outbox item {report.report_id} vanished after insert")
        return InsertedItem(stored, created=True)

    async def get_by_report(self, user_id: str, report_id: str) -> OutboxItemDocument | None:
        """Return the item stored for a report, or None."""
        return await self._find_one({"user_id": user_id, "report_id": report_id})

    async def list_settled_of_series(
        self, user_id: str, series: str, *, before: datetime, limit: int
    ) -> list[OutboxItemDocument]:
        """Return the last items of a series that were told or kept quiet before an instant, newest first."""
        return await self._find(
            {
                "user_id": user_id,
                "report.subject.series": series,
                "report.occurred_at": {"$lt": before},
                "state": {"$in": [ItemState.SENT.value, ItemState.DROPPED.value]},
            },
            sort=[("report.occurred_at", -1)],
            limit=limit,
        )

    async def list_of_series(
        self, user_id: str, series: str, *, limit: int
    ) -> list[OutboxItemDocument]:
        """Return the latest items of a series in any state, newest first."""
        return await self._find(
            {"user_id": user_id, "report.subject.series": series},
            sort=[("report.occurred_at", -1)],
            limit=limit,
        )

    async def apply_replace(self, report: OutboxReport) -> bool:
        """Let the latest report of a subject stand: supersede its older unsent ones, or itself if outranked.

        True when the report is still to be told. Reports of one occurrence time never
        supersede each other.
        """
        subject = {"user_id": report.recipient, "report.subject.id": report.subject.id}
        await self._raw_collection().update_many(
            {
                **subject,
                "report_id": {"$ne": report.report_id},
                "state": {"$in": [state.value for state in UNSENT_STATES]},
                "report.occurred_at": {"$lt": report.occurred_at},
            },
            {
                "$set": {
                    "state": ItemState.SUPERSEDED.value,
                    "superseded_by": report.report_id,
                    "updated_at": clock.now(),
                }
            },
        )
        newer = await self._find_one(
            {
                **subject,
                "report_id": {"$ne": report.report_id},
                "state": {"$in": [state.value for state in _TOLD_OR_TELLING_STATES]},
                "report.occurred_at": {"$gt": report.occurred_at},
            },
            sort=[("report.occurred_at", -1)],
        )
        if newer is None:
            return True
        await self._transition(
            report.recipient,
            {"report_id": report.report_id},
            from_states=[ItemState.RECEIVED],
            changes={"state": ItemState.SUPERSEDED.value, "superseded_by": newer.report_id},
        )
        return False

    async def queue(
        self,
        user_id: str,
        report_id: str,
        *,
        urgency: UrgencyClass,
        mode: ComposeMode,
        judgement: ItemJudgement | None = None,
    ) -> OutboxItemDocument | None:
        """Move a received or held item to queued, keeping what the Judge made of it; None when it was neither."""
        return await self._transition(
            user_id,
            {"report_id": report_id},
            from_states=[ItemState.RECEIVED, ItemState.HELD],
            changes={
                "state": ItemState.QUEUED.value,
                "urgency": int(urgency),
                "mode": mode.value,
                **_judgement_fields(judgement),
            },
        )

    async def hold(
        self,
        user_id: str,
        report_id: str,
        hold: ItemHold,
        *,
        urgency: UrgencyClass,
        mode: ComposeMode,
        judgement: ItemJudgement | None = None,
    ) -> OutboxItemDocument | None:
        """Hold a received or held item until an instant; None when it was neither."""
        return await self._transition(
            user_id,
            {"report_id": report_id},
            from_states=[ItemState.RECEIVED, ItemState.HELD],
            changes={
                "state": ItemState.HELD.value,
                "hold": hold.model_dump(mode="python"),
                "urgency": int(urgency),
                "mode": mode.value,
                **_judgement_fields(judgement),
            },
        )

    async def drop(
        self,
        user_id: str,
        report_id: str,
        reason: DropReason,
        *,
        judgement: ItemJudgement | None = None,
    ) -> OutboxItemDocument | None:
        """Record a received or held item and never alert it; None when it was neither."""
        return await self._transition(
            user_id,
            {"report_id": report_id},
            from_states=[ItemState.RECEIVED, ItemState.HELD],
            changes={
                "state": ItemState.DROPPED.value,
                "drop_reason": reason.value,
                **_judgement_fields(judgement),
            },
        )

    async def list_unsettled(
        self, user_id: str, *, limit: int, exclude_report_id: str | None = None
    ) -> list[OutboxItemDocument]:
        """Return the user's items not yet told or settled, other than one report's, newest first."""
        filter_: dict[str, object] = {
            "user_id": user_id,
            "state": {"$in": [state.value for state in UNSENT_STATES]},
        }
        if exclude_report_id is not None:
            filter_["report_id"] = {"$ne": exclude_report_id}
        return await self._find(filter_, sort=[("created_at", -1)], limit=limit)

    async def list_due_held(
        self, user_id: str, now: datetime, *, limit: int = 0
    ) -> list[OutboxItemDocument]:
        """Return the user's held items whose hold has ended, oldest hold first."""
        return await self._find(
            {"user_id": user_id, "state": ItemState.HELD.value, "hold.until": {"$lte": now}},
            sort=[("hold.until", 1)],
            limit=limit,
        )

    async def list_recovering_queued(self, user_id: str) -> list[OutboxItemDocument]:
        """Return the user's queued items the recovery sweep found stranded, oldest first."""
        return await self._find(
            {
                "user_id": user_id,
                "state": ItemState.QUEUED.value,
                "recovery_attempts": {"$gt": 0},
            },
            sort=[("created_at", 1)],
        )

    async def users_with_due_held(self, now: datetime) -> list[str]:
        """Return the users who have a held item whose hold has ended: the ones a lost flush job left waiting."""
        return await self._raw_collection().distinct(
            "user_id", {"state": ItemState.HELD.value, "hold.until": {"$lte": now}}
        )

    async def count_overdue_held_since_before(self, now: datetime, cutoff: datetime) -> int:
        """Return how many items have been held since before the cutoff although their hold has ended."""
        return await self._count(
            {
                "state": ItemState.HELD.value,
                "hold.since": {"$lt": cutoff},
                "hold.until": {"$lte": now},
            }
        )

    async def claim_recovery(
        self, now: datetime, stale_before: datetime, *, limit: int
    ) -> list[OutboxItemDocument]:
        """Count one recovery attempt on each unsent item untouched since the cutoff; return the ones this call won.

        An attempt moves recovered_at, so an item is driven once per staleness window.
        """
        stale = {
            "state": {
                "$in": [
                    ItemState.RECEIVED.value,
                    ItemState.QUEUED.value,
                    ItemState.COMPOSING.value,
                ]
            },
            "updated_at": {"$lt": stale_before},
            "$or": [{"recovered_at": {"$exists": False}}, {"recovered_at": {"$lt": stale_before}}],
        }
        candidates = await self._raw_collection().find(stale, {"_id": 1}).to_list(length=limit)
        claimed: list[OutboxItemDocument] = []
        for candidate in candidates:
            raw = await self._raw_collection().find_one_and_update(
                {**stale, "_id": candidate["_id"]},
                {"$inc": {"recovery_attempts": 1}, "$set": {"recovered_at": now}},
                return_document=True,
            )
            if raw is not None:
                claimed.append(self._to_model(raw))
        return claimed

    async def fail_exhausted(self, user_id: str, report_id: str) -> OutboxItemDocument | None:
        """Fail an unsent item the recovery sweep gave up on; None when it was told or settled meanwhile."""
        return await self._transition(
            user_id,
            {"report_id": report_id},
            from_states=[ItemState.RECEIVED, ItemState.QUEUED, ItemState.COMPOSING],
            changes={
                "state": ItemState.FAILED.value,
                "failure": ItemFailure.RECOVERY_EXHAUSTED.value,
            },
        )

    async def requeue_composing(self, user_id: str, report_id: str) -> OutboxItemDocument | None:
        """Give an item a dead compose left composing back to the queue; None when it was not composing."""
        return await self._apply_raw_update(
            {"user_id": user_id, "report_id": report_id},
            {
                "$set": {"state": ItemState.QUEUED.value},
                "$unset": {"compose_attempt_id": ""},
            },
            scope=user_id,
            extra_filter={"state": ItemState.COMPOSING.value},
        )

    async def release_held(
        self, user_id: str, reasons: Collection[HoldReason], now: datetime
    ) -> int:
        """End the holds of the user's held items that wait for a reason a return answers; return how many."""
        result = await self._raw_collection().update_many(
            {
                "user_id": user_id,
                "state": ItemState.HELD.value,
                "hold.reason": {"$in": [reason.value for reason in reasons]},
                "hold.until": {"$gt": now},
            },
            {"$set": {"hold.until": now, "updated_at": now}},
        )
        return result.modified_count

    async def list_told_of_fact(
        self, user_id: str, same_fact_key: str, *, since: datetime, limit: int
    ) -> list[OutboxItemDocument]:
        """Return the items that told one real-world fact since the cutoff, newest first."""
        return await self._find(
            {
                "user_id": user_id,
                "judgement.verdict.same_fact_key": same_fact_key,
                "state": ItemState.SENT.value,
                "updated_at": {"$gte": since},
            },
            sort=[("updated_at", -1)],
            limit=limit,
        )

    async def count_raised_interrupts_since(self, user_id: str, since: datetime) -> int:
        """Return how many items the Judge raised to interrupt since the cutoff."""
        return await self._count(
            {
                "user_id": user_id,
                "judgement.raised_interrupt": True,
                "created_at": {"$gte": since},
            }
        )

    async def list_waits(self, user_id: str, *, limit: int) -> list[OutboxItemDocument]:
        """Return the user's latest items the Judge told to wait for a run, newest first."""
        return await self._find(
            {"user_id": user_id, "judgement.verdict.wait_for_run": {"$type": "string"}},
            sort=[("created_at", -1)],
            limit=limit,
        )

    async def list_settled_for_owner(
        self, user_id: str, owner_conversation_id: str, *, limit: int
    ) -> list[OutboxItemDocument]:
        """Return the latest items told or recorded-only for one owner conversation, newest first."""
        return await self._find(
            {
                "user_id": user_id,
                "report.subject.owner_conversation_id": owner_conversation_id,
                "state": {"$in": [ItemState.SENT.value, ItemState.DROPPED.value]},
            },
            sort=[("report.occurred_at", -1)],
            limit=limit,
        )

    async def list_of_attempt(self, user_id: str, attempt_id: str) -> list[OutboxItemDocument]:
        """Return the items one compose attempt took, whatever state they are in now."""
        return await self._find({"user_id": user_id, "compose_attempt_id": attempt_id})

    async def list_feed(
        self,
        user_id: str,
        *,
        states: Collection[ItemState],
        outcomes: Collection[str] | None,
        excluded_outcomes: Collection[str],
        before: datetime | None,
        limit: int,
    ) -> list[OutboxItemDocument]:
        """Return a page of the user's items, newest first: in these states, with these outcomes, without those.

        An outcome is a run report's declared outcome or a notice's, whichever the item's report carries.
        """
        clauses: list[dict[str, object]] = [
            {"user_id": user_id, "state": {"$in": [state.value for state in states]}}
        ]
        if before is not None:
            clauses.append({"created_at": {"$lt": before}})
        if outcomes is not None:
            clauses.append(_outcome_in(outcomes))
        if excluded_outcomes:
            clauses.append({"$nor": [_outcome_in(excluded_outcomes)]})
        return await self._find({"$and": clauses}, sort=[("created_at", -1)], limit=limit)

    async def count_told_since(
        self, user_id: str, since: datetime, *, excluded_outcomes: Collection[str]
    ) -> int:
        """Return how many items were told to the user since the instant, leaving out the outcomes named."""
        return await self._count(
            {
                "$and": [
                    {
                        "user_id": user_id,
                        "state": ItemState.SENT.value,
                        "updated_at": {"$gte": since},
                    },
                    {"$nor": [_outcome_in(excluded_outcomes)]},
                ]
            }
        )

    async def claim_queued(
        self, user_id: str, report_ids: list[str], attempt_id: str
    ) -> list[OutboxItemDocument]:
        """Move the queued ones among the named reports to composing under attempt_id; return the ones this call won."""
        await self._raw_collection().update_many(
            {
                "user_id": user_id,
                "report_id": {"$in": report_ids},
                "state": ItemState.QUEUED.value,
            },
            {
                "$set": {
                    "state": ItemState.COMPOSING.value,
                    "compose_attempt_id": attempt_id,
                    "updated_at": clock.now(),
                }
            },
        )
        return await self._find(
            {
                "user_id": user_id,
                "compose_attempt_id": attempt_id,
                "state": ItemState.COMPOSING.value,
            },
            sort=[("report.occurred_at", 1)],
        )

    async def claim_queued_for_subject(
        self, user_id: str, subject_id: str, attempt_id: str
    ) -> list[OutboxItemDocument]:
        """Move every queued item of a subject to composing under attempt_id; return the ones this call won."""
        await self._raw_collection().update_many(
            {
                "user_id": user_id,
                "report.subject.id": subject_id,
                "state": ItemState.QUEUED.value,
            },
            {
                "$set": {
                    "state": ItemState.COMPOSING.value,
                    "compose_attempt_id": attempt_id,
                    "updated_at": clock.now(),
                }
            },
        )
        return await self._find(
            {
                "user_id": user_id,
                "compose_attempt_id": attempt_id,
                "state": ItemState.COMPOSING.value,
            },
            sort=[("report.occurred_at", 1)],
        )

    async def begin_send(self, user_id: str, attempt_id: str) -> int:
        """Move an attempt's composing items to sending; return how many still were composing."""
        return await self._advance_attempt(
            user_id, attempt_id, ItemState.COMPOSING, {"state": ItemState.SENDING.value}
        )

    async def finish_send(
        self,
        user_id: str,
        attempt_id: str,
        state: Literal[ItemState.SENT, ItemState.FAILED],
        failure: ItemFailure | None = None,
    ) -> int:
        """Settle an attempt's sending items as sent or failed; return how many were sending."""
        changes: dict[str, object] = {"state": state.value}
        if failure is not None:
            changes["failure"] = failure.value
        return await self._advance_attempt(user_id, attempt_id, ItemState.SENDING, changes)

    async def fail_composing(self, user_id: str, attempt_id: str, failure: ItemFailure) -> int:
        """Settle an attempt's composing items as failed: nothing was sent and nothing will retry it."""
        return await self._advance_attempt(
            user_id,
            attempt_id,
            ItemState.COMPOSING,
            {"state": ItemState.FAILED.value, "failure": failure.value},
        )

    async def drop_composing(
        self, user_id: str, attempt_id: str, report_ids: list[str], reason: DropReason
    ) -> int:
        """Record some of an attempt's composing items and never alert them; return how many were composing."""
        result = await self._raw_collection().update_many(
            {
                "user_id": user_id,
                "compose_attempt_id": attempt_id,
                "state": ItemState.COMPOSING.value,
                "report_id": {"$in": report_ids},
            },
            {
                "$set": {
                    "state": ItemState.DROPPED.value,
                    "drop_reason": reason.value,
                    "updated_at": clock.now(),
                }
            },
        )
        return result.modified_count

    async def release_composing(self, user_id: str, attempt_id: str) -> int:
        """Give an attempt's composing items back to the queue, so a retry can claim them."""
        result = await self._raw_collection().update_many(
            {
                "user_id": user_id,
                "compose_attempt_id": attempt_id,
                "state": ItemState.COMPOSING.value,
            },
            {
                "$set": {"state": ItemState.QUEUED.value, "updated_at": clock.now()},
                "$unset": {"compose_attempt_id": ""},
            },
        )
        return result.modified_count

    async def release_sending(self, user_id: str, attempt_id: str) -> int:
        """Give an attempt's sending items back to the queue after nothing reached the user, counting the refusal."""
        result = await self._raw_collection().update_many(
            {
                "user_id": user_id,
                "compose_attempt_id": attempt_id,
                "state": ItemState.SENDING.value,
            },
            {
                "$set": {"state": ItemState.QUEUED.value, "updated_at": clock.now()},
                "$unset": {"compose_attempt_id": ""},
                "$inc": {"transport_retries": 1},
            },
        )
        return result.modified_count

    async def _advance_attempt(
        self, user_id: str, attempt_id: str, from_state: ItemState, changes: dict[str, object]
    ) -> int:
        result = await self._raw_collection().update_many(
            {"user_id": user_id, "compose_attempt_id": attempt_id, "state": from_state.value},
            {"$set": {**changes, "updated_at": clock.now()}},
        )
        return result.modified_count

    async def _transition(
        self,
        user_id: str,
        match: dict[str, object],
        *,
        from_states: list[ItemState],
        changes: dict[str, object],
    ) -> OutboxItemDocument | None:
        return await self._apply_raw_update(
            {"user_id": user_id, **match},
            {"$set": changes},
            scope=user_id,
            extra_filter={"state": {"$in": [state.value for state in from_states]}},
        )


outbox_items_repository = OutboxItemsRepository()
