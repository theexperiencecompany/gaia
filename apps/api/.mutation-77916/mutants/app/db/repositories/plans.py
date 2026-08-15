"""Repository for the ``subscription_plans`` collection — the global plan catalog.

Global (not user-scoped), keyed by Mongo ``_id``. Seeded by scripts and read-only
in the app. The plan-list cache in the payment service (a non-entity Redis cache
of ``PlanResponse`` shapes) stays where it is, so this repository holds no policy.
"""

from app.db.repositories.base import MongoRepository
from app.models.payment_models import PlanDocument, PlanUpdate


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


plan_repository = PlansRepository()
