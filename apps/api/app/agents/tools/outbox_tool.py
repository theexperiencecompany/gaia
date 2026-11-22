"""Comms' view of the outbox and its hand on it: what waits to be told and why, what was decided, and the user's say over an untold update.

The text is for comms, not the user: each update carries a ref the change tool takes, and the
reasons are named plainly so comms can explain them in the user's terms.
"""

from datetime import datetime
from typing import Annotated, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools.core.mutations import define_mutation_tool, user_id_from_config
from app.constants.outbox import OUTBOX_VIEW_EXCERPT_CHARS
from app.constants.outbox_attention import HoldReason
from app.models.attention_settings_models import AttentionSettings
from app.models.quiet_hours_models import QuietHours
from app.models.updates_models import UpdateRow
from app.services.outbox.judge_context import user_clock
from app.services.outbox.models import DropReason, ItemState
from app.services.outbox.overview import OutboxOverview, read_outbox_overview
from app.services.outbox.user_actions import cancel_update, send_now, tell_at
from app.utils.auth_utils import load_user_context
from app.utils.timezone import Timezone

#: Why an update waits, as comms may explain it.
HOLD_REASONS: dict[HoldReason, str] = {
    HoldReason.QUIET_HOURS: "quiet hours",
    HoldReason.DND: "do not disturb",
    HoldReason.NOT_BEFORE: "the time it was set to be told",
    HoldReason.CHECKIN: "the next check-in (not urgent, or today's unprompted updates are used up)",
    HoldReason.GAP: "a gap after the last unprompted update",
    HoldReason.WAIT_FOR_RUN: "a run due soon that may change it",
    HoldReason.IN_CALL: "the user's call to end",
    HoldReason.DORMANT: "the user's return or the weekly email (they have been away)",
    HoldReason.BAD_MOMENT: "a better moment",
    HoldReason.USER_SET: "the time the user asked for",
}

#: Why an update was recorded and not sent, as comms may explain it.
DROP_REASONS: dict[DropReason, str] = {
    DropReason.NOTHING_NEW: "nothing new",
    DropReason.CANCELLED: "the work was cancelled",
    DropReason.COMPOSE_SKIPPED: "it added nothing the user needed",
    DropReason.NOT_WATCHING: "progress nobody was watching",
    DropReason.EXPIRED: "it stopped mattering before it could be told",
    DropReason.USER_MUTED: "the user turned these updates off",
    DropReason.ALREADY_KNOWN: "the user already knew",
    DropReason.MOOT: "it no longer mattered",
    DropReason.SUPERSEDED: "a newer update replaced it",
    DropReason.DUPLICATE: "it repeated what was already said",
    DropReason.UNWANTED: "the user's rules say not to tell it",
    DropReason.REPEAT_BACKOFF: "told recently; it waits longer before being repeated",
    DropReason.LEAK_UNRESOLVED: "it could not be worded properly",
    DropReason.DIGESTED: "it went in the weekly email",
    DropReason.ASKED_AS_APPROVAL: "its approval request asks instead",
    DropReason.USER_CANCELLED: "the user asked not to be told",
}


def _when(instant: datetime, timezone: Timezone) -> str:
    return timezone.localize(instant).strftime("%a %d %b %H:%M")


def describe_attention(
    settings: AttentionSettings,
    quiet: QuietHours,
    chat_app_order: list[str],
    timezone: Timezone,
) -> list[str]:
    """Return the user's attention settings as lines comms can read back to them."""
    dnd = (
        f"until {_when(settings.dnd_until, timezone)}" if settings.dnd_until is not None else "off"
    )
    checkins = ", ".join(t.strftime("%H:%M") for t in settings.checkin_times) or "none"
    rules = "; ".join(f'"{rule}"' for rule in settings.rules) or "none"
    return [
        f"- Unprompted updates allowed per day: {settings.max_unsolicited_per_day}",
        f"- Quiet hours: {quiet.start_hour:02d}:00-{quiet.end_hour:02d}:00 "
        f"({'on' if quiet.enabled else 'off'})",
        f"- Check-in times: {checkins} (and when quiet hours end)",
        f"- Do not disturb: {dnd}",
        f"- The user's rules about what to tell them: {rules}",
        f"- Chat apps, first choice first: {', '.join(chat_app_order)}",
    ]


def _gist(row: UpdateRow) -> str:
    said = row.display.line if row.display is not None else "; ".join(row.facts)
    return said[:OUTBOX_VIEW_EXCERPT_CHARS]


def _waiting_line(row: UpdateRow, timezone: Timezone) -> str:
    why = HOLD_REASONS[row.hold_reason] if row.hold_reason is not None else "its turn"
    until = f", until {_when(row.held_until, timezone)}" if row.held_until is not None else ""
    return f'- [ref {row.report_id}] "{row.subject_label}": {_gist(row)} | waits for {why}{until}'


def _recent_line(row: UpdateRow, timezone: Timezone) -> str:
    at = _when(row.told_at or row.created_at, timezone)
    if row.state is ItemState.SENT and row.told:
        told = " ".join(row.told)[:OUTBOX_VIEW_EXCERPT_CHARS]
        return f'- {at} "{row.subject_label}": told "{told}"'
    if row.state is ItemState.DROPPED and row.drop_reason is not None:
        return f'- {at} "{row.subject_label}": not told, {DROP_REASONS[row.drop_reason]}'
    return f'- {at} "{row.subject_label}": {row.state.value}'


def describe_outbox(overview: OutboxOverview) -> str:
    """Return the outbox as comms reads it."""
    tz = overview.timezone
    next_checkin = _when(overview.next_checkin, tz) if overview.next_checkin is not None else "none"
    waiting = [_waiting_line(row, tz) for row in overview.waiting] or ["- nothing"]
    recent = [_recent_line(row, tz) for row in overview.recent] or ["- nothing yet"]
    upcoming = [f'- {u.kind} "{u.label}": {_when(u.at, tz)}' for u in overview.upcoming] or [
        "- nothing scheduled"
    ]
    lines = [
        "Settings:",
        *describe_attention(overview.settings, overview.quiet_hours, overview.chat_app_order, tz),
        f"- Unprompted updates told today: {overview.told_unprompted_today}; "
        f"next check-in: {next_checkin}",
        "",
        "Waiting to be told:",
        *waiting,
        "",
        "Latest decisions, newest first:",
        *recent,
        "",
        "Coming up (tracked todos' next runs are in your context):",
        *upcoming,
    ]
    return "\n".join(lines)


@tool
async def read_outbox(config: RunnableConfig) -> str:
    """Read what GAIA will tell the user on its own and when: their settings, updates waiting and why, recent decisions, and what is scheduled.

    Use it when the user asks what is coming, why they were or were not told something, when
    they will hear about something, or what their notification settings are. Never show the refs.
    """
    user_id = user_id_from_config(config)
    if not user_id:
        return "Error: user authentication required."
    user = await load_user_context(user_id)
    if user is None:
        return "Error: user not found."
    return describe_outbox(await read_outbox_overview(user))


class ChangeUpdateArgs(BaseModel):
    """What the user asked to do with one update GAIA has not told yet."""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(description="The update's ref, from read_outbox.")
    action: Literal["send_now", "tell_at", "cancel"] = Field(
        description=(
            "send_now: tell it right after this reply, whatever holds it. tell_at: tell it at "
            "the time the user named, even in quiet hours. cancel: never tell it."
        )
    )
    at: Annotated[
        datetime | None,
        Field(
            description=(
                "For tell_at only: when, as an ISO datetime, with the user's offset when they "
                "named a timezone and without it for their own clock."
            )
        ),
    ] = None


async def _change_update(user_id: str, **fields: object) -> str:
    args = ChangeUpdateArgs.model_validate(fields)
    match args.action:
        case "send_now":
            changed = await send_now(user_id, args.ref)
        case "cancel":
            changed = await cancel_update(user_id, args.ref)
        case "tell_at":
            if args.at is None:
                return "Not changed: tell_at needs the time to tell it."
            at = args.at
            if at.tzinfo is None:
                user = await load_user_context(user_id)
                if user is None:
                    return "Error: user not found."
                at = at.replace(tzinfo=user_clock(user).timezone.tzinfo)
            changed = await tell_at(user_id, args.ref, at)
    if not changed:
        return "Not changed: that update was already told, or is being told now."
    return "Done."


change_update = define_mutation_tool(
    name="change_update",
    area="outbox",
    description=(
        "Do what the user asked with an update GAIA has not told yet: tell it now, tell it at "
        "a time they name, or never tell it. The user's word overrides quiet hours, do not "
        "disturb and the daily limit. Find the ref with read_outbox first."
    ),
    args_model=ChangeUpdateArgs,
    apply=_change_update,
)

tools = [read_outbox, change_update]
