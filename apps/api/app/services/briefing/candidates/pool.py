"""Gather every producer's candidates for one brief, daily or weekly, numbered once and deduplicated."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.constants.briefing import GAIA_SOURCE
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import BriefingEvent, UnreadSource
from app.models.scout_models import ScoutOutcome
from app.services.briefing.candidates.app_signals import app_signal_candidates
from app.services.briefing.candidates.approvals import approval_candidates
from app.services.briefing.candidates.calendar import calendar_candidates
from app.services.briefing.candidates.failed_runs import failed_run_candidates
from app.services.briefing.candidates.held import held_candidates
from app.services.briefing.candidates.judge import CandidatePool
from app.services.briefing.candidates.reminders import reminder_candidates
from app.services.briefing.candidates.subjects import same_text_key
from app.services.briefing.candidates.tracked import (
    gaia_work_candidates,
    user_done_candidates,
    waiting_candidates,
)
from app.services.briefing.context import CompletedWork, TrackedWork, UserClock, day_start_utc
from app.services.briefing.scouts.service import ScoutSignals


@dataclass(frozen=True)
class GatheredCandidates:
    """The numbered pool, the held results it folded into another candidate, and what was read.

    duplicate_held_ids are held results saying what another candidate already says: the
    brief accounts for them, so they are cleared with it.
    """

    pool: dict[int, BriefCandidate]
    duplicate_held_ids: list[str]
    sources_read: list[str]
    sources_unavailable: list[UnreadSource]

    @property
    def has_news(self) -> bool:
        """Whether anything besides the calendar is in the pool."""
        return any(c.kind is not CandidateKind.EVENT for c in self.pool.values())


@dataclass(frozen=True)
class CandidateSources:
    """What the daily run already read, which the producers turn into candidates."""

    work: TrackedWork
    held: list[PendingBriefItemDocument]
    scouts: ScoutSignals
    calendar: list[BriefingEvent]


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


def _apps_in(pool: CandidatePool) -> list[str]:
    return [c.app for c in pool.values() if c.source != GAIA_SOURCE]


def _sources(scouts: ScoutSignals, pool: CandidatePool) -> tuple[list[str], list[UnreadSource]]:
    read = [r.app for r in scouts.results if r.outcome is not ScoutOutcome.SKIPPED]
    read += _apps_in(pool)
    unavailable = [
        UnreadSource(app=r.app, reason=r.skip_reason)
        for r in scouts.results
        if r.skip_reason is not None
    ]
    return list(dict.fromkeys(read)), unavailable


async def gather_candidates(
    user_id: str, clock: UserClock, since: datetime, now: datetime, sources: CandidateSources
) -> GatheredCandidates:
    """Run every producer, needs-you sources first, and number what they found."""
    work = sources.work
    day_start = day_start_utc(clock)
    open_todo_ids = {doc.id for doc in [*work.blocked, *work.failed, *work.running]}
    candidates = [
        *waiting_candidates(work),
        *await approval_candidates(user_id, now, open_todo_ids),
        *await reminder_candidates(user_id, day_start, day_start + timedelta(days=1)),
        *await failed_run_candidates(user_id, since),
        *app_signal_candidates(sources.scouts.remembered, now),
        *await held_candidates(user_id, sources.held),
        *gaia_work_candidates(work),
        *calendar_candidates(sources.calendar),
    ]
    pool, duplicates = _numbered(candidates)
    read, unavailable = _sources(sources.scouts, pool)
    return GatheredCandidates(pool, duplicates, read, unavailable)


async def gather_week_candidates(
    user_id: str, since: datetime, completed: CompletedWork, ahead: list[BriefingEvent]
) -> GatheredCandidates:
    """Run the producers over the week since Monday: failed runs, what got done, the week ahead."""
    candidates = [
        *await failed_run_candidates(user_id, since),
        *user_done_candidates(completed.user),
        *gaia_work_candidates(TrackedWork(completed=completed.gaia)),
        *calendar_candidates(ahead),
    ]
    pool, duplicates = _numbered(candidates)
    return GatheredCandidates(pool, duplicates, list(dict.fromkeys(_apps_in(pool))), [])
