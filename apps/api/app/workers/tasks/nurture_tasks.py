"""Nurture email ARQ task."""

from typing import Any

from app.services.nurture import run_nurture_sequence


async def run_nurture_sequence_task(ctx: dict[str, Any]) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """Hourly sweep: send due nurture emails to users at their local send hour.

    The wide-event boundary comes from ``arq_task`` (the envelope worker.py
    wraps every task in); an inner ``wide_task`` here would emit a second
    canonical event per run.
    """
    return await run_nurture_sequence()
