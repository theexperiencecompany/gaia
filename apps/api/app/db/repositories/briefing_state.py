"""Repository for the briefing_state collection: one row per user, keyed by user_id (unique).

Every write is an upsert, so a user's row appears with the first thing stored for them
and a missing row reads as every default. No cache: briefs and the briefing settings
read it a few times a day, never per request.
"""

from datetime import UTC, datetime

from app.constants.briefing import BriefingBag
from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.briefing_state_models import (
    BriefingBootstrap,
    BriefingStateDocument,
    BriefingStateUpdate,
    DayZeroHello,
    ShuffleBag,
)

# $unset reads only the field names; the value is ignored.
_UNSET = ""


class BriefingStateRepository(MongoRepository[BriefingStateDocument, BriefingStateUpdate]):
    collection_name = "briefing_state"
    document_model = BriefingStateDocument
    update_model = BriefingStateUpdate
    uses_object_id = False
    identity_field = "user_id"
    cache_policy = None

    async def state_for(self, user_id: str) -> BriefingStateDocument:
        """Return the user's briefing state; a user nothing was stored for has every default."""
        return await self.get(user_id) or BriefingStateDocument(user_id=user_id)

    async def _set(self, user_id: str, fields: dict[str, object]) -> None:
        await self._apply_raw_update_unfetched(  # pragma: no mutate — no cache to evict
            {"user_id": user_id}, {"$set": fields}, scope=REPO_GLOBAL_SCOPE, upsert=True
        )

    async def _unset(self, user_id: str, *fields: str) -> None:
        await self._apply_raw_update_unfetched(  # pragma: no mutate — no cache to evict
            {"user_id": user_id},
            {"$unset": dict.fromkeys(fields, _UNSET)},  # pragma: no mutate — $unset ignores values
            scope=REPO_GLOBAL_SCOPE,
        )

    async def set_bag(self, user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        """Persist one shuffle bag's advanced state (see shuffle_bag.draw)."""
        await self._set(user_id, {f"shuffle_bags.{bag.value}": state.model_dump()})

    async def hold_for_goal(self, user_id: str) -> None:
        """Hold the user's briefs until a goal arrives or the grace window elapses.

        Only a user with no hold yet is stamped, so a re-run never restarts a running window.
        """
        hold = BriefingBootstrap(pending=True, since=datetime.now(UTC)).model_dump()
        await self._apply_pipeline_update_unfetched(
            {"user_id": user_id},
            [{"$set": {"bootstrap": {"$ifNull": ["$bootstrap", {"$literal": hold}]}}}],
            scope=None,
            upsert=True,
        )

    async def clear_bootstrap(self, user_id: str) -> None:
        """Clear the goal hold once a real brief goes out."""
        await self._unset(user_id, "bootstrap")

    async def set_idle_day(self, user_id: str, *, idle_days: int, date_str: str) -> None:
        """Persist today's idle/active outcome on the idle ladder."""
        await self._set(user_id, {"dormancy.idle_days": idle_days, "dormancy.date": date_str})

    async def enter_dormancy(self, user_id: str) -> None:
        """Stamp now as when the brief loop went dormant."""
        await self._set(user_id, {"dormancy.dormant_since": datetime.now(UTC)})

    async def record_goal_question(self, user_id: str) -> None:
        """Stamp now as when a brief last asked whether the user's goal is still live."""
        await self._set(user_id, {"dormancy.goal_asked_at": datetime.now(UTC)})

    async def clear_dormancy(self, user_id: str) -> None:
        """Wake the loop: clear the idle streak and dormancy, keeping when a goal was last asked about."""
        await self._unset(user_id, "dormancy.dormant_since", "dormancy.idle_days", "dormancy.date")

    async def mark_day_zero_hello_sent(self, user_id: str, platform: str) -> None:
        """Record that GAIA's first text after a platform link went out, and where."""
        hello = DayZeroHello(sent_at=datetime.now(UTC), platform=platform)
        await self._set(user_id, {"day_zero_hello": hello.model_dump()})


briefing_state_repository = BriefingStateRepository()
