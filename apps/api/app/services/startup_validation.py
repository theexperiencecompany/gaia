"""
Startup validation for GAIA.
"""

from shared.py.wide_events import log
from app.core.lazy_loader import lazy_provider
from app.db.mongodb.collections import (
    ai_models_collection,
    plans_collection,
)


# @Cacheable(key="startup:models_seeded", ttl=2592000)  # 30 days cache
async def are_models_seeded() -> bool:
    """Check if AI models are seeded in database."""
    count = await ai_models_collection.count_documents({})
    return count > 0


# @Cacheable(key="startup:payment_setup", ttl=2592000)  # 30 days cache
async def is_payment_setup() -> bool:
    """Check if payment plans are set up in database."""
    count = await plans_collection.count_documents({})
    return count > 0


@lazy_provider(
    "startup_validation",
    required_keys=[],
    is_global_context=False,
    auto_initialize=True,
)
async def validate_startup_requirements():
    """Check if models are seeded and payment is set up."""
    log.set(service="startup_validation", phase="startup")
    try:
        log.info("Starting startup scripts validation...")
        # Check models and payment plans
        models_ok = await are_models_seeded()
        payment_ok = await is_payment_setup()

        # Log results and halt startup if requirements are not met
        if not models_ok or not payment_ok:
            log.error("Setup incomplete! Please run: ./scripts/setup.sh")
            if not models_ok:
                log.error("❌ AI models not seeded")
            if not payment_ok:
                log.error("❌ Payment plans not set up")
            raise RuntimeError(
                "Startup requirements not met. Please run: ./scripts/setup.sh"
            )

    except Exception as e:
        log.error(f"Startup validation failed: {e}")
