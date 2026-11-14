"""ARQ cron task: finish what dead processes left on the conversations the step runs."""

from collections.abc import Mapping

from app.services.conversation.sweeper import sweep_conversations


async def sweep_step_conversations(ctx: Mapping[str, object]) -> str:  # noqa: ARG001 -- contract
    """Flush stranded entries, log lost work and start steps for unanswered inputs."""
    report = await sweep_conversations()
    return f"flushed={report.flushed} lost={report.lost_work} kicked={report.kicked}"
