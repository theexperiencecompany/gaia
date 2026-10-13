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
        try:
            return await self._apply_raw_update(
                {"user_id": user_id, "$and": conditions},
                {"$set": {"last_nudged_at": now, _sent_field(nudge): now}},
                scope=REPO_GLOBAL_SCOPE,
                upsert=True,
            )
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
        restore: dict[str, dict[str, object]] = {
            "$set": {"last_nudged_at": prior.last_nudged_at if prior else None}
        }
        if prior_sent is None:
            restore["$unset"] = {_sent_field(nudge): ""}
        else:
            restore["$set"][_sent_field(nudge)] = prior_sent
        await self._apply_raw_update_unfetched(
            {"user_id": user_id, _sent_field(nudge): claimed_at},
            restore,
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def stamp(self, user_id: str, nudge: ReferralNudge, now: datetime) -> None:
        """Record a message that is never held back, starting a new window from it."""
        await self._apply_raw_update_unfetched(
            {"user_id": user_id},
            {"$set": {"last_nudged_at": now, _sent_field(nudge): now}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
            upsert=True,
        )

    async def record_dismissal(
        self, user_id: str, now: datetime, *, dismissals_to_pause: int, pause: timedelta
    ) -> ReferralNudgeStateDocument:
        """Count a dismissed nudge; the one that reaches dismissals_to_pause pauses every nudge and restarts the count."""
        counted = await self._apply_raw_update(
            {"user_id": user_id},
            {"$inc": {"dismissals": 1}},
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
        )
        if counted is None or counted.dismissals < dismissals_to_pause:
            return self._require(counted, user_id)
        paused = await self._apply_raw_update(
            {"user_id": user_id, "dismissals": {"$gte": dismissals_to_pause}},
            {"$set": {"dismissals": 0, "paused_until": now + pause}},
            scope=REPO_GLOBAL_SCOPE,
        )
        # A concurrent dismissal already took the pause; read what it left.
        return self._require(paused or await self.get(user_id), user_id)

    @staticmethod
    def _require(
        state: ReferralNudgeStateDocument | None, user_id: str
    ) -> ReferralNudgeStateDocument:
        if state is None:
            raise RuntimeError(f"referral nudge state for {user_id} vanished mid-update")
        return state


referral_nudge_repository = ReferralNudgesRepository()
