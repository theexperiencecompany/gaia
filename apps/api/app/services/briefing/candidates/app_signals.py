"""App signals as candidates: what the scouts found in the user's connected apps."""

from collections.abc import Sequence
from datetime import datetime

from app.models.brief_candidate_models import BriefCandidate
from app.models.scout_models import RememberedSignal
from app.services.briefing.scouts.facts import memory_note


def _detail(item: RememberedSignal, now: datetime) -> str:
    signal = item.signal
    parts = [f"{signal.kind}"]
    if signal.state:
        parts.append(f"state: {signal.state}")
    if signal.why:
        parts.append(f"why: {signal.why}")
    parts.append(memory_note(item, now))
    return " | ".join(parts)


def app_signal_candidates(
    remembered: Sequence[RememberedSignal], now: datetime
) -> list[BriefCandidate]:
    """Return one candidate per signal, with what earlier briefs remember of it in its detail."""
    return [
        BriefCandidate(
            source=item.signal.integration_id,
            app=item.signal.app,
            state="you",
            title=item.signal.title,
            detail=_detail(item, now),
            people=list(item.signal.people),
            due_at=item.signal.due_at,
            url=item.signal.url,
            importance=item.signal.importance,
            signal=item.signal,
            ref=f"{item.signal.integration_id}:{item.signal.external_id}",
        )
        for item in remembered
    ]
