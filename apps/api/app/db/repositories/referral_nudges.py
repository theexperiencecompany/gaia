"""Repository for the referral_nudges collection: one row per user, the budget every referral nudge draws on.

Keyed by user_id (unique). A claim is one conditional upsert, so two channels
nudging the same user at once cannot both win the week.
"""

from datetime import datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.constants.referrals import ReferralNudge
from app.db.repositories.base import MongoRepository
from app.models.referral_models import ReferralNudgeStateDocument


def _sent_field(nudge: ReferralNudge) -> str:
    return f"sent_at.{nudge.value}"


class ReferralNudgesRepository(
    MongoRepository[ReferralNudgeStateDocument, ReferralNudgeStateDocument]
):
    collection_name = "referral_nudges"
    document_model = ReferralNudgeStateDocument
    update_model = ReferralNudgeStateDocument
    uses_object_id = True
    identity_field = "user_id"
    cache_policy = None

    async def claim(
        self,
        user_id: str,
        nudge: ReferralNudge,
        now: datetime,
        *,
        window_start: datetime,
        once: bool,
    ) -> ReferralNudgeStateDocument | None:
        """Take the user's nudge slot; None when one went out since window_start, they paused, or a once-only nudge already went."""
        conditions: list[dict[str, object]] = [
            {"$or": [{"last_nudged_at": None}, {"last_nudged_at": {"$lte": window_start}}]},
            {"$or": [{"paused_until": None}, {"paused_until": {"$lte": now}}]},
        ]
        if once:
            conditions.append({_sent_field(nudge): {"$exists": False}})
        free = {"user_id": user_id, "$and": conditions}
        take = {"$set": {"last_nudged_at": now, _sent_field(nudge): now}}
        try:
            # pragma: no mutate start — cache_policy is None, so scope keys nothing
            return await self._apply_raw_update(free, take, scope=REPO_GLOBAL_SCOPE, upsert=True)
            # pragma: no mutate end
        except DuplicateKeyError:
            # The row exists and refused the filter: the slot is taken.
            return None

    async def release(
        self,
        user_id: str,
        nudge: ReferralNudge,
        claimed_at: datetime,
        *,
        prior: ReferralNudgeStateDocument | None,
    ) -> None:
        """Hand back a claim whose message never went out, restoring the state from before it."""
        prior_sent = prior.sent_at.get(nudge) if prior else None
        restored: dict[str, object] = {"last_nudged_at": prior.last_nudged_at if prior else None}
        restore: dict[str, dict[str, object]] = {"$set": restored}
        if prior_sent is None:
            # pragma: no mutate start — $unset ignores the value
            restore["$unset"] = {_sent_field(nudge): ""}
            # pragma: no mutate end
        else:
            restored[_sent_field(nudge)] = prior_sent
        ours = {"user_id": user_id, _sent_field(nudge): claimed_at}
        # pragma: no mutate start — cache_policy is None, so scope and doc_id key nothing
        await self._apply_raw_update_unfetched(
            ours, restore, scope=REPO_GLOBAL_SCOPE, doc_id=user_id
        )
        # pragma: no mutate end

    async def stamp(self, user_id: str, nudge: ReferralNudge, now: datetime) -> None:
        """Record a message that is never held back, starting a new window from it."""
        mine = {"user_id": user_id}
        stamped = {"$set": {"last_nudged_at": now, _sent_field(nudge): now}}
        # pragma: no mutate start — cache_policy is None, so scope and doc_id key nothing
        await self._apply_raw_update_unfetched(
            mine, stamped, scope=REPO_GLOBAL_SCOPE, doc_id=user_id, upsert=True
        )
        # pragma: no mutate end

    async def record_dismissal(
        self, user_id: str, now: datetime, *, dismissals_to_pause: int, pause: timedelta
    ) -> ReferralNudgeStateDocument:
        """Count a dismissed nudge; the one that reaches dismissals_to_pause pauses every nudge and restarts the count."""
        mine = {"user_id": user_id}
        one_more = {"$inc": {"dismissals": 1}}
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        counted = await self._apply_raw_update(mine, one_more, scope=REPO_GLOBAL_SCOPE, upsert=True)
        # pragma: no mutate end
        state = self._require(counted, user_id)  # pragma: no mutate — upsert always returns a row
        if state.dismissals < dismissals_to_pause:
            return state
        due = {"user_id": user_id, "dismissals": {"$gte": dismissals_to_pause}}
        paused = {"$set": {"dismissals": 0, "paused_until": now + pause}}
        # pragma: no mutate start — cache_policy is None, so scope and doc_id key nothing
        await self._apply_raw_update_unfetched(due, paused, scope=REPO_GLOBAL_SCOPE, doc_id=user_id)
        # pragma: no mutate end
        # Read back rather than trust the update: a concurrent dismissal may have taken the pause.
        latest = await self.get(user_id)
        return self._require(latest, user_id)  # pragma: no mutate — the row exists

    @staticmethod
    def _require(
        state: ReferralNudgeStateDocument | None, user_id: str
    ) -> ReferralNudgeStateDocument:
        if state is None:
            raise RuntimeError(f"referral nudge state for {user_id} vanished mid-update")
        return state


referral_nudge_repository = ReferralNudgesRepository()
