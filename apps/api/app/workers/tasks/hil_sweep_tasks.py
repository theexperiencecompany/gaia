"""ARQ cron task: resolve expired HIL approvals, remind about ledger ones, re-dispatch crashed resumes."""

from collections.abc import Mapping

from app.services.hil.ledger_sweep import LedgerSweepCounts, sweep_ledger_approvals
from app.services.hil.resolution import SweepCounts, sweep_approvals
from shared.py.wide_events import log


async def sweep_hil_approvals(ctx: Mapping[str, object]) -> str:  # noqa: ARG001 -- contract
    """Every-minute sweep: sweep_approvals for parked runs, sweep_ledger_approvals for ledger asks."""
    counts: SweepCounts = await sweep_approvals()
    ledger: LedgerSweepCounts = await sweep_ledger_approvals()
    log.set(
        expired_count=counts["expired"],
        redispatched_count=counts["redispatched"],
        ledger_expired_count=ledger["expired"],
        ledger_reminded_count=ledger["reminded"],
    )
    return (
        f"expired={counts['expired']} redispatched={counts['redispatched']} "
        f"ledger_expired={ledger['expired']} ledger_reminded={ledger['reminded']}"
    )
