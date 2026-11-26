"""The quiet note: what a brief says instead of an edition when nothing new needs the reader."""

from dataclasses import dataclass, field, replace
from datetime import date

from app.constants.briefing import (
    QUIET_NOTE_CALENDAR_UNREAD,
    QUIET_NOTE_NO_CALENDAR,
    QUIET_NOTE_OVERDUE,
    QUIET_NOTE_SIGNED_OUT,
    QUIET_NOTE_SIGNED_OUT_MANY,
    QUIET_NOTE_STILL,
    QUIET_NOTE_STILL_FOR,
    QUIET_NOTE_STILL_SINCE,
    QUIET_NOTE_UNREAD,
    QUIET_NOTE_UNREAD_HEADLINE,
    QUIET_NOTE_UNREAD_SHOWN,
    QUIET_NOTE_WATCH,
    BriefForm,
    BriefingKind,
)
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefingModel
from app.models.brief_payload_models import BriefingMood, BriefingPayload, UnreadSource
from app.models.scout_models import ScoutSkipReason
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.clock import UserClock, when_sent
from app.services.briefing.formats import listed
from app.services.briefing.kinds import BriefKindSpec


@dataclass(frozen=True)
class QuietFacts:
    """What a quiet note says beside its quiet: the calendar, the quiet it continues, overdue.

    still_quiet says the brief of its kind before it was a quiet note too; last_edition is the
    last drawn brief of any kind, None when none ever went out.
    """

    calendar: CalendarGap | None
    overdue: int = 0
    #: The connected apps that went unread, and why: the quiet is only of what was read.
    unread: list[UnreadSource] = field(default_factory=list)
    still_quiet: bool = False
    last_edition: BriefingModel | None = None

    def apps_unread(self, *reasons: ScoutSkipReason) -> list[str]:
        """Return each unread app once, in order; only those unread for one of reasons, when given."""
        return list(dict.fromkeys(s.app for s in self.unread if not reasons or s.reason in reasons))


def last_was_quiet(recent: list[BriefingModel], kind: BriefingKind) -> bool:
    """Say whether the latest brief of its kind, of the recent ones newest first, was a quiet note."""
    previous = next((b for b in recent if b.kind == kind), None)
    return previous is not None and previous.payload.form is BriefForm.QUIET_NOTE


async def continued(
    user_id: str, kind: BriefingKind, recent: list[BriefingModel], facts: QuietFacts
) -> QuietFacts:
    """Say how the quiet stands: after a quiet brief of its kind, since which edition it goes on."""
    if not last_was_quiet(recent, kind):
        return facts
    editions = await briefing_repository.list_recent(user_id, limit=1, editions_only=True)
    return replace(facts, still_quiet=True, last_edition=editions[0] if editions else None)


def _quiet_news(spec: BriefKindSpec, facts: QuietFacts, clock: UserClock) -> str:
    """Say there is nothing new; after a quiet brief, since which brief and how many days ago."""
    if not facts.still_quiet:
        return QUIET_NOTE_UNREAD_HEADLINE if facts.unread else spec.quiet.nothing_new
    edition = facts.last_edition
    if edition is None:
        return QUIET_NOTE_STILL
    when = when_sent(edition, clock)
    days = (clock.today - date.fromisoformat(edition.date)).days
    if days == 1:
        return QUIET_NOTE_STILL_SINCE.format(when=when)
    return QUIET_NOTE_STILL_FOR.format(days=days, when=when)


def quiet_note(clock: UserClock, spec: BriefKindSpec, facts: QuietFacts) -> BriefingPayload:
    """Write a quiet brief's note from its facts: nothing new, the calendar, what is past due."""
    calendar = {
        None: spec.quiet.calendar_clear,
        CalendarGap.NOT_CONNECTED: QUIET_NOTE_NO_CALENDAR,
        CalendarGap.UNAVAILABLE: QUIET_NOTE_CALENDAR_UNREAD,
    }[facts.calendar]
    lines = [f"{_quiet_news(spec, facts, clock)}{calendar}"]
    signed_out = facts.apps_unread(ScoutSkipReason.SIGNED_OUT)
    # A signed-out app has its own line, so the unread line names only the rest.
    if others := [app for app in facts.apps_unread() if app not in signed_out]:
        lines.append(QUIET_NOTE_UNREAD.format(apps=listed(others, QUIET_NOTE_UNREAD_SHOWN)))
    if signed_out:
        reconnect = QUIET_NOTE_SIGNED_OUT_MANY if len(signed_out) > 1 else QUIET_NOTE_SIGNED_OUT
        lines.append(reconnect.format(apps=listed(signed_out)))
    if facts.overdue:
        lines.append(QUIET_NOTE_OVERDUE.format(count=facts.overdue))
    lines.append(QUIET_NOTE_WATCH)
    return BriefingPayload(
        form=BriefForm.QUIET_NOTE,
        kicker=spec.kicker,
        date=clock.date_str,
        headline=QUIET_NOTE_UNREAD_HEADLINE if facts.unread else spec.quiet.headline,
        lede="",
        caption="",
        mood=BriefingMood.IDLE,
        template_family=None,
        message="\n".join(lines),
        sources_unavailable=facts.unread,
    )
