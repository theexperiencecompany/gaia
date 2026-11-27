"""App signals as candidates: what the scouts found in the user's connected apps."""

from collections.abc import Sequence
import math

from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin, OutsideRef
from app.models.brief_item_models import ItemState
from app.models.scout_models import RememberedSignal, SignalImportance
from app.services.briefing.clock import UserClock
from app.services.briefing.scouts.facts import memory_note
from app.utils.timezone import as_utc


def _detail(item: RememberedSignal, clock: UserClock) -> str:
    signal = item.signal
    parts = [signal.kind]
    if signal.state:
        parts.append(f"{signal.app} shows it as {signal.state}")
    if signal.why:
        parts.append(f"why: {signal.why}")
    parts.append(memory_note(item, clock))
    return " | ".join(parts)


def _rank(item: RememberedSignal) -> tuple[bool, float]:
    """Order signals by the scout's urgency, then by how recently the app saw them move, undated last."""
    signal = item.signal
    touched = as_utc(signal.updated_at or signal.created_at)
    recency = touched.timestamp() if touched is not None else -math.inf
    return (signal.importance is not SignalImportance.HIGH, -recency)


def _passed_over(item: RememberedSignal) -> bool:
    """Whether an earlier brief saw this undated row, left it out, and nothing has changed since."""
    memory, signal = item.memory, item.signal
    if memory is None or memory.times_shown or item.previous_state is not None:
        return False
    updated, seen = as_utc(signal.updated_at), as_utc(memory.last_seen)
    edited_since = updated is not None and seen is not None and updated > seen
    return signal.due_at is None and not edited_since


def app_signal_candidates(
    remembered: Sequence[RememberedSignal], clock: UserClock
) -> list[BriefCandidate]:
    """Return one candidate per signal not passed over before, important then most recently moved first."""
    return [
        BriefCandidate(
            origin=CandidateOrigin.APP_SIGNAL,
            source=item.signal.integration_id,
            app=item.signal.app,
            state=ItemState.YOU,
            title=item.signal.title,
            detail=_detail(item, clock),
            people=list(item.signal.people),
            due_at=item.signal.due_at,
            url=item.signal.url,
            importance=item.signal.importance,
            signal=item.signal,
            ref=OutsideRef(
                integration_id=item.signal.integration_id,
                external_id=item.signal.external_id,
            ),
            memory=item.memory,
            moved=item.previous_state is not None,
        )
        for item in sorted(remembered, key=_rank)
        if not _passed_over(item)
    ]
