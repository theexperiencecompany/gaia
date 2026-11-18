"""Gather every producer's candidates for one brief, daily or weekly, numbered once and deduplicated."""

from dataclasses import dataclass, field
from datetime import datetime

from app.constants.briefing import GAIA_SOURCE
from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_candidate_models import BriefCandidate, OutsideRef
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import BriefingEvent, UnreadSource
from app.models.scout_models import SignalImportance
from app.models.todo_models import TodoDocument
from app.services.briefing.candidates.app_signals import app_signal_candidates
from app.services.briefing.candidates.approvals import approval_candidates
from app.services.briefing.candidates.calendar import calendar_candidates
from app.services.briefing.candidates.failed_runs import failed_run_candidates
from app.services.briefing.candidates.held import held_candidates
from app.services.briefing.candidates.memory import remember_candidates
from app.services.briefing.candidates.reminders import reminder_candidates
from app.services.briefing.candidates.subjects import same_text_key
from app.services.briefing.candidates.tracked import (
    gaia_work_candidates,
    own_todo_candidates,
    user_done_candidates,
    waiting_candidates,
)
from app.services.briefing.clock import UserClock
from app.services.briefing.scouts.service import ScoutSignals
from app.services.briefing.work import TrackedWork
from app.services.integrations.user_integrations import get_connected_integration_ids


@dataclass(frozen=True)
class GatheredCandidates:
    """The numbered pool, the held results it folded into another candidate, and what went unread.

    duplicate_held_ids are held results saying what another candidate already says: the
    brief accounts for them, so they are cleared with it.
    """

    pool: dict[int, BriefCandidate]
    duplicate_held_ids: list[str]
    sources_unavailable: list[UnreadSource]

    @property
    def has_news(self) -> bool:
        """Whether the pool holds anything the user has not been told: no event, backlog or repeat."""
        return any(c.is_news for c in self.pool.values())


@dataclass(frozen=True)
class CandidateSources:
    """What the run already read, which the producers turn into candidates.

    due_before is when the brief's span ends: a reminder or a dated todo of their own due
    before it is the brief's. user_done is what the user finished themselves, which only
    the weekly recaps.
    """

    work: TrackedWork
    scouts: ScoutSignals
    calendar: list[BriefingEvent]
    due_before: datetime
    #: Every open todo of the user's own, from the run's one read of the todos store.
    open_own: list[TodoDocument]
    #: The results held for the daily brief; the weekly carries none.
    held: list[PendingBriefItemDocument] = field(default_factory=list)
    user_done: list[TodoDocument] = field(default_factory=list)


def _found_by(candidate: BriefCandidate) -> str:
    return f"the {candidate.app} scout" if candidate.signal is not None else candidate.app


def _merged(first: BriefCandidate, again: BriefCandidate) -> BriefCandidate:
    """Fold a second source's find of the same thing into the first, keeping what only it knew."""
    high = SignalImportance.HIGH in (first.importance, again.importance)
    return first.model_copy(
        update={
            "detail": first.detail or again.detail,
            "people": list(dict.fromkeys([*first.people, *again.people])),
            "due_at": first.due_at or again.due_at,
            "url": first.url or again.url,
            "importance": SignalImportance.HIGH if high else first.importance,
            "todo_id": first.todo_id or again.todo_id,
            "held_id": first.held_id or again.held_id,
            "signal": first.signal or again.signal,
            "also_in": [*first.also_in, _found_by(again), *again.also_in],
        }
    )


def _one_per_thing(candidates: list[BriefCandidate]) -> list[BriefCandidate]:
    """Fold candidates about the same outside thing into one, in the order each was first found."""
    by_ref: dict[OutsideRef, int] = {}
    kept: list[BriefCandidate] = []
    for candidate in candidates:
        if candidate.ref is not None and candidate.ref in by_ref:
            index = by_ref[candidate.ref]
            kept[index] = _merged(kept[index], candidate)
            continue
        if candidate.ref is not None:
            by_ref[candidate.ref] = len(kept)
        kept.append(candidate)
    return kept


def _numbered(candidates: list[BriefCandidate]) -> tuple[dict[int, BriefCandidate], list[str]]:
    """Give each candidate its id from 1, folding a held result into any candidate with its title."""
    seen = {same_text_key(c.title) for c in candidates if c.held_id is None}
    pool: dict[int, BriefCandidate] = {}
    duplicates: list[str] = []
    for candidate in candidates:
        if candidate.held_id is not None:
            key = same_text_key(candidate.title)
            if key in seen:
                duplicates.append(candidate.held_id)
                continue
            seen.add(key)
        pool[len(pool) + 1] = candidate
    return pool, duplicates


#: GAIA's built-in surfaces it writes to once connected: its own work, mail drafts, calendar events.
_BUILT_IN_WRITERS = frozenset({GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID})


async def _acting_sources(user_id: str, scouts: ScoutSignals) -> set[str]:
    """Return the sources GAIA can act in: its own work, its connected built-ins, apps with write tools."""
    connected = await get_connected_integration_ids(user_id)
    return {
        GAIA_SOURCE,
        *(_BUILT_IN_WRITERS & set(connected)),
        *(r.integration_id for r in scouts.results if r.can_write),
    }


def _unavailable(scouts: ScoutSignals) -> list[UnreadSource]:
    return [
        UnreadSource(app=r.app, reason=r.skip_reason)
        for r in scouts.results
        if r.skip_reason is not None
    ]


async def gather_candidates(
    user_id: str, clock: UserClock, since: datetime, now: datetime, sources: CandidateSources
) -> GatheredCandidates:
    """Run every producer, needs-you sources first, remember each find, and number them."""
    work = sources.work
    day_start = clock.day_start()
    day_end = sources.due_before
    open_todo_ids = {doc.id for doc in [*work.blocked, *work.failed, *work.running]}
    candidates = [
        *waiting_candidates(work),
        *await approval_candidates(user_id, now, open_todo_ids),
        *await reminder_candidates(user_id, day_start, day_end),
        *own_todo_candidates(sources.open_own, day_end, work),
        *await failed_run_candidates(user_id, since),
        *app_signal_candidates(sources.scouts.remembered, clock),
        *await held_candidates(user_id, sources.held),
        *user_done_candidates(sources.user_done),
        *gaia_work_candidates(work, clock),
        *calendar_candidates(sources.calendar, clock.date_str),
    ]
    acting = await _acting_sources(user_id, sources.scouts)
    candidates = [c.model_copy(update={"gaia_acts": c.source in acting}) for c in candidates]
    remembered = await remember_candidates(user_id, _one_per_thing(candidates), now)
    pool, duplicates = _numbered(remembered)
    return GatheredCandidates(pool, duplicates, _unavailable(sources.scouts))
