"""A scout follows its integration: learned in the background on connect, dropped on disconnect.

Kept apart from the scout service: the connect and disconnect paths import this, and the
service reaches the agent stack and integration modules that import those paths back.
"""

from app.constants.scouts import LEARN_SCOUT_TASK
from app.db.repositories.scouts import scouts_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job


async def queue_scout_learn(user_id: str, integration_id: str) -> None:
    """Enqueue a learn so the next brief already scouts a newly connected integration."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        LEARN_SCOUT_TASK,
        user_id,
        integration_id,
        _job_id=f"{LEARN_SCOUT_TASK}:{user_id}:{integration_id}",
    )


async def forget_integration(user_id: str, integration_id: str) -> None:
    """Drop a disconnected integration's scout and everything the brief remembered from it."""
    await scouts_repository.delete_for(user_id, integration_id)
    await signal_memory_repository.delete_for_integration(user_id, integration_id)
