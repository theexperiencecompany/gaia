"""Reading the user's attention: the facts the Rails place an item against, and the placement they give.

The reads live here and the rules in holds.place, which is pure: this module only gathers
what the user's day looks like now (settings, who is here, what GAIA already told them) and
hands it over.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.constants.outbox_attention import REPEAT_BACKOFF_SECONDS, REPEAT_MUTE_SECONDS
from app.db.repositories.attention_settings import attention_settings_repository
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.user_models import AuthenticatedUser
from app.services.delivery.presence import read_call_room, read_last_active
from app.services.outbox.deliver import OutboxUserNotFoundError
from app.services.outbox.dormancy import is_dormant
from app.services.outbox.holds import AttentionState, FactHistory, Placement, place
from app.services.outbox.judge_context import user_clock
from app.services.outbox.judge_models import JudgeVerdict
from app.services.outbox.models import ComposeMode, ItemHold, OutboxReport, UrgencyClass
from app.utils import clock
from app.utils.auth_utils import load_user_context
from app.utils.timezone import as_utc


async def _fact_history(
    user_id: str, verdict: JudgeVerdict | None, now: datetime
) -> FactHistory | None:
    if verdict is None or verdict.same_fact_key is None:
        return None
    told = await outbox_items_repository.list_told_of_fact(
        user_id,
        verdict.same_fact_key,
        since=now - timedelta(seconds=REPEAT_MUTE_SECONDS),
        limit=len(REPEAT_BACKOFF_SECONDS) + 1,
    )
    last_told_at = as_utc(told[0].updated_at) if told else None
    return FactHistory(len(told), last_told_at) if last_told_at is not None else None


async def attention_state(
    user: AuthenticatedUser,
    verdict: JudgeVerdict | None,
    *,
    now: datetime,
    prior_hold: ItemHold | None,
) -> AttentionState:
    """Return what the user's attention looks like now: their settings, who is here, and what they were told today."""
    user_id = user.user_id
    user_clock_ = user_clock(user)
    local = user_clock_.timezone.localize(now)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    (
        settings,
        last_active,
        call_room,
        told_today,
        last_unsolicited_at,
        history,
    ) = await asyncio.gather(
        attention_settings_repository.read(user_id),
        read_last_active(user_id),
        read_call_room(user_id),
        outbox_messages_repository.count_sent_since(user_id, day_start, ComposeMode.UNSOLICITED),
        outbox_messages_repository.last_sent_at(user_id, ComposeMode.UNSOLICITED),
        _fact_history(user_id, verdict, now),
    )
    return AttentionState(
        user_id=user_id,
        now=now,
        clock=user_clock_,
        settings=settings,
        last_active_at=datetime.fromtimestamp(last_active, UTC)
        if last_active is not None
        else None,
        in_call=call_room is not None,
        dormant=await is_dormant(user_id, last_active, now),
        unsolicited_today=told_today,
        last_unsolicited_at=as_utc(last_unsolicited_at),
        fact_history=history,
        prior_hold=prior_hold,
    )


async def place_item(
    report: OutboxReport,
    urgency: UrgencyClass,
    verdict: JudgeVerdict | None,
    *,
    prior_hold: ItemHold | None = None,
    released: bool = False,
) -> Placement:
    """Return when an item the policy decided to tell is told, against the user's attention now."""
    user = await load_user_context(report.recipient)
    if user is None:
        raise OutboxUserNotFoundError(report.recipient)
    state = await attention_state(user, verdict, now=clock.now(), prior_hold=prior_hold)
    return place(report, urgency, verdict, state, released=released)
