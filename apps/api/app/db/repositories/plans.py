"""Repository for the subscription_plans collection — the global plan catalog.

Global (not user-scoped), keyed by Mongo _id. Seeded by scripts and read-only
in the app. The plan-list cache in the payment service (a non-entity Redis cache
of PlanResponse shapes) stays where it is, so this repository holds no policy.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.payment_models import PlanDocument, PlanTier, PlanUpdate

#: A row written before plan rows carried their tier.
_UNTAGGED: dict[str, object] = {"plan_type": {"$exists": False}}


class PlansRepository(MongoRepository[PlanDocument, PlanUpdate]):
    collection_name = "subscription_plans"
    document_model = PlanDocument
    update_model = PlanUpdate
    uses_object_id = True
    cache_policy = None

    async def list_plans(self, *, active_only: bool = True) -> list[PlanDocument]:
        """All plans (or only active ones), cheapest first."""
        filter_: dict[str, object] = {"is_active": True} if active_only else {}
        return await self._find(filter_, sort=[("amount", 1)])

    async def tag_one_untagged(self, name: str, plan_type: PlanTier) -> bool:
        """Tag one untagged row with this name; False once none is left."""
        matched = await self._apply_raw_update_unfetched(
            {"name": name, **_UNTAGGED},
            {"$set": {"plan_type": plan_type.value}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def untagged_names(self) -> list[str]:
        """Names of the rows that still carry no tier."""
        return await self._distinct("name", _UNTAGGED)


plan_repository = PlansRepository()
