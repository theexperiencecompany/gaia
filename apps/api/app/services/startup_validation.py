"""
Startup validation for GAIA.
"""

from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.db.repositories.plans import plan_repository
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

    if await is_payment_setup():
        return

    remedies = [f"Payment plans not set up — run: {SEED_PLANS_COMMAND}"]

    log.error("Setup incomplete!")
    for remedy in remedies:
        log.error(remedy)
    raise RuntimeError("Startup requirements not met. " + " ".join(remedies))
