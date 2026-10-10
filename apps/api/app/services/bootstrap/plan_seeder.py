"""Free-plan auto-seed for instances without a payment provider.

Hosted GAIA is paid-only and never gets a Free row; this exists solely so a
self-hosted instance has a plan row to exist against. There its limits are
tracked but never enforced (billing_enabled is False), which is what makes that
instance effectively unlimited — see build_plan_catalogue.
"""

from app.db.repositories.plans import plan_repository
from app.services.bootstrap.plan_catalogue import build_plan_catalogue
from shared.py.wide_events import log


async def seed_free_plan_if_missing() -> bool:
    """Seed the Free plan when the plan catalogue is empty.

    Self-host instances have no payment provider so the startup gate would refuse
    to boot; idempotent no-op when any plan exists, True when a seed happened.
    """
    if await plan_repository.count() > 0:
        return False
    free = build_plan_catalogue(monthly_product_id="", yearly_product_id="", include_free=True)[0]
    await plan_repository.create(free)
    log.info("Seeded default Free plan")
    return True
