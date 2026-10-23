"""Learn the brief scout of an integration the user just connected, before their next brief."""

from app.db.repositories.users import user_repository
from app.services.briefing.scouts.service import learn_connected_integration
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log


async def learn_scout_task(_ctx: ArqJobContext, user_id: str, integration_id: str) -> str:
    """Scout the new integration once; a failure raises so the job records it."""
    log.set(user_id=user_id, integration_id=integration_id)
    user = await user_repository.get(user_id)
    if user is None:
        raise LookupError(f"no user {user_id} to scout {integration_id} for")
    result = await learn_connected_integration(user, integration_id)
    outcome = result.outcome.value if result is not None else "not_scouted"
    log.set_ns("scouts", learn_outcome=outcome)
    return f"learn_scout {integration_id}: {outcome}"
