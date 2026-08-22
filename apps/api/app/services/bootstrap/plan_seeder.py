"""Free-plan auto-seed for instances without a payment provider."""

from app.db.repositories.plans import plan_repository
from app.services.bootstrap.plan_catalogue import build_plan_catalogue
from shared.py.wide_events import log


async def seed_free_plan_if_missing() -> bool:
    """Seed the Free plan when the plan catalogue is empty.

    Self-host instances have no payment provider, so the Dodo setup script can
    never provision them — without this row the startup gate refuses to boot.
    Callers decide policy (``validate_startup_requirements`` invokes this only
    when no Dodo key is configured); the function itself is pure mechanics and
    idempotent: a no-op when any plan exists. Returns True when a seed
    happened."""
    if await plan_repository.count() > 0:
        return False
    free = build_plan_catalogue(monthly_product_id="", yearly_product_id="")[0]
    await plan_repository.create(free)
    log.info("Seeded default Free plan")
    return True
