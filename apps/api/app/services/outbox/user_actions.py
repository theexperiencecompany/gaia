"""What the user asks GAIA to do with an update it has not told yet: tell it now, at a time, or never.

The user's word overrides the outbox's own timing: a time they chose is kept even in quiet
hours or past the day's budget. Only an untold item can be changed; one already told or being
told is left alone and the call says so.
"""

from datetime import datetime, timedelta

from app.constants.outbox_attention import RETURN_FLUSH_DELAY_SECONDS, HoldReason
from app.constants.websocket import ReportSettledOutcome
from app.db.repositories.outbox_items import outbox_items_repository
from app.services.outbox.flush_queue import schedule_flush
from app.services.outbox.models import DropReason, ItemHold, ItemState
from app.services.outbox.policy import decide
from app.services.outbox.settled import announce_settled
from app.utils import clock


async def tell_at(user_id: str, report_id: str, at: datetime) -> bool:
    """Hold an untold update until the instant the user chose and tell it then; False when it is no longer untold."""
    item = await outbox_items_repository.get_by_report(user_id, report_id)
    if item is None or item.state not in {ItemState.RECEIVED, ItemState.HELD}:
        return False
    now = clock.now()
    # An item still in the batch window was never judged: the producer's own urgency stands.
    producer = decide(item.report, None)
    held = await outbox_items_repository.hold(
        user_id,
        report_id,
        ItemHold(
            reason=HoldReason.USER_SET,
            until=max(at, now),
            since=item.hold.since if item.hold is not None else now,
        ),
        urgency=item.urgency if item.urgency is not None else producer.urgency,
        mode=item.mode if item.mode is not None else producer.mode,
    )
    if held is None:
        return False
    await schedule_flush(user_id, max(at, now))
    return True


async def send_now(user_id: str, report_id: str) -> bool:
    """Tell an untold update right after the reply the user is reading; False when it is no longer untold."""
    return await tell_at(
        user_id, report_id, clock.now() + timedelta(seconds=RETURN_FLUSH_DELAY_SECONDS)
    )


async def cancel_update(user_id: str, report_id: str) -> bool:
    """Record an untold update and never tell it; False when it is no longer untold."""
    dropped = await outbox_items_repository.drop(user_id, report_id, DropReason.USER_CANCELLED)
    if dropped is None:
        return False
    await announce_settled(dropped.report, ReportSettledOutcome.RECORDED)
    return True
