"""Repository for the ``subscriptions`` collection.

Global (webhook updates key on ``dodo_subscription_id`` with no user in scope) —
``user_id`` is a plain field with named finders. Identity is Mongo's ``_id`` so
the status endpoint keeps returning the same id it always did; the Dodo-keyed
paths are named methods. ``updated_at`` is snake_case, so the base stamps it on
every write automatically.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.payment_models import SubscriptionDocument, SubscriptionUpdate


class SubscriptionsRepository(MongoRepository[SubscriptionDocument, SubscriptionUpdate]):
    collection_name = "subscriptions"
    document_model = SubscriptionDocument
    update_model = SubscriptionUpdate
    uses_object_id = True
    cache_policy = None

    async def get_active_for_user(self, user_id: str) -> SubscriptionDocument | None:
        return await self._find_one({"user_id": user_id, "status": "active"})

    async def get_latest_active_for_user(self, user_id: str) -> SubscriptionDocument | None:
        found = await self._find(
            {"user_id": user_id, "status": "active"}, sort=[("created_at", -1)], limit=1
        )
        return found[0] if found else None

    async def get_by_dodo_id(self, dodo_subscription_id: str) -> SubscriptionDocument | None:
        return await self._find_one({"dodo_subscription_id": dodo_subscription_id})

    async def get_user_id_by_dodo_id(self, dodo_subscription_id: str) -> str | None:
        subscription = await self._find_one({"dodo_subscription_id": dodo_subscription_id})
        return subscription.user_id if subscription is not None else None

    async def apply_update_by_dodo_id(self, dodo_subscription_id: str, **fields: object) -> bool:
        """Apply a ``$set`` patch to the subscription with this Dodo id, returning
        whether one matched. ``updated_at`` is auto-stamped by the base, so callers
        pass only the fields that actually change."""
        if not fields:
            return False
        updated = await self._apply_raw_update(
            {"dodo_subscription_id": dodo_subscription_id},
            {"$set": dict(fields)},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None


subscription_repository = SubscriptionsRepository()
