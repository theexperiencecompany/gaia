"""Tag catalogue rows written before plan rows carried their tier.

Runs on every boot from the startup gate, so a deploy never waits on a manual
script: it is idempotent (only untagged rows match) and safe across pods (each
write is one conditional update). A row it cannot classify stops the boot.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.plans import plan_repository
from app.models.payment_models import PlanTier
from shared.py.wide_events import log

#: The names payment_setup.py has ever seeded, and the tier each one sells.
LEGACY_PLAN_TIERS: dict[str, PlanTier] = {
    "Pro": PlanTier.PRO,
    "Enterprise": PlanTier.ENTERPRISE,
    "Free": PlanTier.FREE,
}


async def backfill_plan_tiers() -> int:
    """Tag every untagged legacy row and return how many were tagged; raise if any row is left."""
    tagged = 0
    for name, tier in LEGACY_PLAN_TIERS.items():
        while await plan_repository.tag_one_untagged(name, tier):
            tagged += 1

    leftover = await plan_repository.untagged_names()
    if leftover:
        raise RuntimeError(
            f"Plan rows with no plan_type and no known tier: {sorted(leftover)}. "
            "Tag them with scripts/payment_setup.py --apply."
        )
    log.info(f"{LogTag.PAYMENT} Plan catalogue tiers backfilled", plans_tagged=tagged)
    return tagged
