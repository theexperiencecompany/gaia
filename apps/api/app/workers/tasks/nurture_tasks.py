"""Nurture email ARQ task."""

from shared.py.wide_events import wide_task


async def run_nurture_sequence_task(ctx: dict) -> str:
    """Hourly sweep: send due nurture emails to users at their local send hour."""
    async with wide_task("run_nurture_sequence"):
        from app.services.nurture import run_nurture_sequence

        return await run_nurture_sequence()
