"""What the outbox looks like for one user right now: their settings, what waits, what was decided lately, and what is due.

The one read behind comms' view of the outbox. Rows come from the Updates feed, so comms
and the Updates page never disagree about an item.
"""

from dataclasses import dataclass
from datetime import datetime

from app.constants.outbox import OUTBOX_VIEW_RECENT_ITEMS, OUTBOX_VIEW_UPCOMING_ITEMS
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.workflows import workflow_repository
from app.models.attention_settings_models import AttentionSettings
from app.models.quiet_hours_models import QuietHours
from app.models.reminder_models import StaticReminderPayload
from app.models.updates_models import UpdateFilter, UpdateRow
from app.models.user_models import AuthenticatedUser
from app.services.delivery.chat_channel import get_chat_channel_priority
from app.services.outbox.attention import attention_state
from app.services.outbox.holds import next_checkin
from app.services.outbox.models import ItemState
from app.services.outbox.updates import read_updates
from app.utils import clock
from app.utils.timezone import Timezone

#: What a reminder is called when its payload has no title of its own.
REMINDER_LABEL_FALLBACK = "Reminder"


@dataclass(frozen=True, slots=True)
class Upcoming:
    """One scheduled thing that will run on its own: what it is called and when."""

    kind: str
    label: str
    at: datetime


@dataclass(frozen=True, slots=True)
class OutboxOverview:
    """The user's outbox at one instant, in their own time zone."""

    timezone: Timezone
    settings: AttentionSettings
    quiet_hours: QuietHours
    chat_app_order: list[str]
    #: The next time GAIA tells what waited for a check-in; None when the user has no check-ins.
    next_checkin: datetime | None
    told_unprompted_today: int
    waiting: list[UpdateRow]
    recent: list[UpdateRow]
    upcoming: list[Upcoming]


async def _upcoming(user_id: str, now: datetime) -> list[Upcoming]:
    reminders = [
        Upcoming(
            "reminder",
            r.payload.title
            if isinstance(r.payload, StaticReminderPayload)
            else REMINDER_LABEL_FALLBACK,
            r.scheduled_at,
        )
        for r in await reminder_repository.find_scheduled_for_user(user_id)
        if r.scheduled_at is not None and r.scheduled_at >= now
    ]
    workflows = [
        Upcoming("workflow", w.title, w.scheduled_at)
        for w in await workflow_repository.find_activated_for_user(user_id)
        if w.scheduled_at is not None and w.scheduled_at >= now
    ]
    return sorted([*reminders, *workflows], key=lambda u: u.at)[:OUTBOX_VIEW_UPCOMING_ITEMS]


async def read_outbox_overview(user: AuthenticatedUser) -> OutboxOverview:
    """Return the user's outbox now: settings, the updates still waiting, the latest decisions and what is due next."""
    now = clock.now()
    state = await attention_state(user, None, now=now, prior_hold=None)
    held = await read_updates(
        user.user_id, UpdateFilter.HELD, before=None, limit=OUTBOX_VIEW_RECENT_ITEMS
    )
    latest = await read_updates(
        user.user_id, UpdateFilter.ALL, before=None, limit=OUTBOX_VIEW_RECENT_ITEMS
    )
    return OutboxOverview(
        timezone=state.clock.timezone,
        settings=state.settings,
        quiet_hours=state.clock.quiet_hours,
        chat_app_order=await get_chat_channel_priority(user.user_id),
        next_checkin=next_checkin(state),
        told_unprompted_today=state.unsolicited_today,
        waiting=held.updates,
        recent=[row for row in latest.updates if row.state is not ItemState.HELD],
        upcoming=await _upcoming(user.user_id, now),
    )
