"""What the daily brief looks back over: the last brief, what got done and ran since, and whether the user came back."""

from dataclasses import dataclass
from datetime import datetime

from app.constants.briefing import LOOKBACK_MAX_DAYS, WINBACK_THRESHOLD, BriefingKind
from app.constants.todos import TodoCompleter
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.models.brief_document_models import BriefingModel
from app.models.brief_payload_models import BriefingMood
from app.models.todo_models import TodoDocument
from app.models.user_models import UserDocument
from app.services.briefing import wind_down
from app.services.briefing.clock import UserClock, when_sent
from app.services.briefing.work import BriefReads, finished_by
from app.utils.timezone import as_utc

# Background workflow runs the look-back lists, newest first.
_LOOKBACK_EXECUTIONS_LIMIT = 20
#: The daily briefs winback counts back over.
_WINBACK_RECENT = 10


async def last_brief(user_id: str, clock: UserClock, kind: BriefingKind) -> BriefingModel | None:
    """Return the latest brief of kind before today; a same-day re-run looks past its own."""
    return await briefing_repository.get_before_date(user_id, kind=kind, before_date=clock.date_str)


async def last_brief_made(user_id: str, clock: UserClock) -> datetime | None:
    """Return when the latest brief before today, daily or weekly, was made; None before any."""
    last = await briefing_repository.get_before_date(user_id, kind=None, before_date=clock.date_str)
    return None if last is None else _created(last)


def lookback_since(clock: UserClock, last: BriefingModel | None) -> datetime:
    """Return when the look-back starts: the last brief, at most LOOKBACK_MAX_DAYS back.

    With no brief before, it starts at yesterday's local midnight.
    """
    if last is None:
        return clock.day_start(days_ago=1)
    return max(_created(last), clock.day_start(days_ago=LOOKBACK_MAX_DAYS))


def _created(brief: BriefingModel) -> datetime:
    return as_utc(brief.created_at)


def _title(doc: TodoDocument) -> str:
    return doc.title or "untitled"


def _closed_how(doc: TodoDocument) -> str:
    if finished_by(doc) is TodoCompleter.TRIGGER:
        return "Closed when an event it watched fired"
    return "Closed (who closed it is not recorded)"


@dataclass(frozen=True)
class Lookback:
    """The brief the look-back starts from and when it starts."""

    last: BriefingModel | None
    since: datetime


async def format_lookback_block(
    user_id: str, reads: BriefReads, lookback: Lookback, clock: UserClock
) -> str:
    """Return what the last brief planned, then what got done and ran since it.

    A brief older than LOOKBACK_MAX_DAYS is named by its date but not quoted: its plan is stale.
    """
    last, since = lookback.last, lookback.since
    completed = reads.completed.since(since)
    executions = await workflow_executions_repository.list_since(
        user_id,
        since,
        exclude_workflow_ids=reads.rhythm_workflow_ids,
        limit=_LOOKBACK_EXECUTIONS_LIMIT,
    )

    parts: list[str] = []
    if last is None:
        parts.append("No prior briefing — this is the first look-back.")
    elif _created(last) < since:
        parts.append(
            f"The last brief went out {when_sent(last, clock)}, over {LOOKBACK_MAX_DAYS} days "
            f"ago; what it said is stale, so this looks back over the last {LOOKBACK_MAX_DAYS} days."
        )
    else:
        told = [
            f"- {item.kind.label.lower()}: {item.text}"
            for section in last.payload.sections
            for item in section.items
            if item.text
        ]
        if told:
            parts.append(
                f"Your last brief, {when_sent(last, clock)}, told the user about:\n"
                + "\n".join(told)
            )

    if completed.gaia or completed.user or completed.closed:
        done = [f"- GAIA finished: {_title(d)}" for d in completed.gaia]
        done += [f"- The user finished: {_title(d)}" for d in completed.user]
        done += [f"- {_closed_how(d)}: {_title(d)}" for d in completed.closed]
        parts.append("Actually completed since then:\n" + "\n".join(done))
    else:
        parts.append("Nothing was completed since the last briefing.")

    if executions:
        # workflow_executions carries no workflow_title field; "Workflow" is the
        # generic label every run has used for as long as the field's been gone.
        ex_lines = [
            f"- Workflow [{d.status}]" + (f": {d.summary}" if d.summary else "") for d in executions
        ]
        parts.append("Background workflow runs since then:\n" + "\n".join(ex_lines))

    return "\n\n".join(parts)


@dataclass
class WinbackState:
    unacknowledged: int
    last_was_winback: bool

    @property
    def is_winback(self) -> bool:
        return self.unacknowledged >= WINBACK_THRESHOLD

    @property
    def should_back_off(self) -> bool:
        # A winback already went out and the user is still silent — don't repeat
        # it the next day; back off until there's activity.
        return self.last_was_winback and self.unacknowledged >= WINBACK_THRESHOLD


async def compute_winback_state(user: UserDocument) -> WinbackState:
    """Count consecutive most-recent daily briefings the user never acknowledged.

    Acknowledged means the user acted on any surface since it went out; opening the
    brief is such an act. A todo completing is NOT an ack: GAIA completes its own todos,
    so winback would never fire. The user's last activity is read once.
    """
    briefings = await briefing_repository.list_recent(
        user.id, limit=_WINBACK_RECENT, kind=BriefingKind.DAILY
    )
    if not briefings:
        return WinbackState(unacknowledged=0, last_was_winback=False)

    last_active = await wind_down.latest_activity_since(user.id, _created(briefings[-1]))
    unacknowledged = 0
    for briefing in briefings:
        if last_active is not None and last_active >= _created(briefing):
            break
        unacknowledged += 1

    last_was_winback = briefings[0].payload.mood is BriefingMood.WINBACK
    return WinbackState(unacknowledged=unacknowledged, last_was_winback=last_was_winback)
