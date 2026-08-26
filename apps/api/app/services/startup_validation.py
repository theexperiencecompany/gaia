"""
Startup validation for GAIA.
"""

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.db.repositories.plans import plan_repository
from app.services.bootstrap.plan_seeder import seed_free_plan_if_missing
from shared.py.wide_events import log

SEED_PLANS_COMMAND = (
    "uv run --group backend python scripts/payment_setup.py "
    "--monthly-product-id <dodo_id> --yearly-product-id <dodo_id>"
)


# @Cacheable(key="startup:payment_setup", ttl=2592000)  # 30 days cache
async def is_payment_setup() -> bool:
    """Check if payment plans are set up in database."""
    return await plan_repository.count() > 0


@lazy_provider(
    "startup_validation",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    is_global_context=False,
    auto_initialize=True,
)
async def validate_startup_requirements() -> None:
    """Halt startup when payment plans are not seeded.

    Registered ``strategy=ERROR``, so raising here aborts a blocking boot (see
    ``provider_registration.unified_startup``) with an actionable message instead
    of letting the app come up misconfigured. A prior broad ``except`` caught this
    very ``RuntimeError`` and only logged it, so the check never actually halted —
    the raise must propagate.
    """
    log.set(component="startup_validation", phase="startup")
    log.info("Starting startup scripts validation...")

    payment_ok = await is_payment_setup()
    if not payment_ok and not settings.DODO_PAYMENTS_API_KEY:
        # No payment provider configured (selfhost/dev): the Dodo setup script
        # cannot run at all, so provision the Free row instead of demanding it.
        # With Dodo configured this never fires — a Dodo instance missing its
        # plans is a real misconfiguration and keeps the remedy below.
        payment_ok = await seed_free_plan_if_missing()
        if not payment_ok:
            # The seeder returns False only when plans already exist (another
            # process seeded between the two counts), so booting is correct.
            payment_ok = await is_payment_setup()
    if payment_ok:
        return

    # Only a Dodo-configured instance reaches the raise: without a key, the
    # seeder above either provisioned the Free row or confirmed plans exist.
    remedies = [f"Payment plans not set up — run: {SEED_PLANS_COMMAND}"]

    log.error("Setup incomplete!")
    for remedy in remedies:
        log.error(remedy)
    raise RuntimeError("Startup requirements not met. " + " ".join(remedies))
