"""ARQ cron task: finish what dead processes left on the conversations the step runs."""

from collections.abc import Mapping

from arq import cron
from arq.cron import CronJob

from app.constants.conversation import SWEEP_SECONDS
from app.services.conversation.sweeper import sweep_conversations
from app.workers.task_envelope import arq_task


async def sweep_step_conversations(ctx: Mapping[str, object]) -> str:  # noqa: ARG001 -- contract
    """Flush stranded entries, log lost work and start steps for unanswered inputs."""
    report = await sweep_conversations()
    return f"flushed={report.flushed} lost={report.lost_work} kicked={report.kicked}"


def conversation_sweep_cron() -> CronJob:
    """Return the sweep that answers a step-run conversation a dead process left, and reports its lost work."""
    return cron(arq_task(sweep_step_conversations), second=set(SWEEP_SECONDS))
