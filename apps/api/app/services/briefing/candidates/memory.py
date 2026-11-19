"""What earlier briefs remember of each candidate, so a thing already told reads as still open, not news.

App signals are remembered by their scout pass, which reads them; every other candidate
the daily pool holds is remembered here, under GAIA's own key for it.
"""

from collections.abc import Sequence
from datetime import datetime

from app.constants.briefing import GAIA_SOURCE
from app.db.repositories.signal_memory import signal_memory_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.scout_models import Sighting


def sighting(candidate: BriefCandidate) -> Sighting | None:
    """Return how memory keys the candidate; None for what is new each time (events, held results)."""
    if candidate.signal is not None:
        signal = candidate.signal
        return Sighting(signal.integration_id, signal.external_id, signal.state)
    if candidate.todo_id is not None:
        return Sighting(GAIA_SOURCE, f"todo:{candidate.todo_id}", candidate.state)
    if candidate.seen_as is not None:
        return Sighting(GAIA_SOURCE, candidate.seen_as, candidate.state)
    return None


async def remember_candidates(
    user_id: str, candidates: Sequence[BriefCandidate], now: datetime
) -> list[BriefCandidate]:
    """Return each candidate with its memory as it stood before today, then record today's sighting."""
    keyed = {
        i: seen
        for i, c in enumerate(candidates)
        if c.signal is None and (seen := sighting(c)) is not None
    }
    if not keyed:
        return list(candidates)
    known = {
        (m.integration_id, m.external_id): m
        for m in await signal_memory_repository.find_for(user_id, list(keyed.values()))
    }
    remembered: list[BriefCandidate] = []
    for i, candidate in enumerate(candidates):
        seen = keyed.get(i)
        memory = known.get((seen.integration_id, seen.external_id)) if seen else None
        if memory is None:
            remembered.append(candidate)
            continue
        moved = memory.last_state not in (None, candidate.state)
        remembered.append(candidate.model_copy(update={"memory": memory, "moved": moved}))
    await signal_memory_repository.record_seen(user_id, list(keyed.values()), now)
    return remembered


async def mark_placed_shown(user_id: str, placed: Sequence[BriefCandidate], now: datetime) -> None:
    """Record that the brief showed every placed candidate memory keys, named in its message or not."""
    await signal_memory_repository.mark_shown(
        user_id, [seen for c in placed if (seen := sighting(c)) is not None], now
    )
