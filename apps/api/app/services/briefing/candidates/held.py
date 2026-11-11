"""Held results as candidates: what a workflow or todo run kept for the brief, the inbox desk's findings among them.

A held report is carried by its first line alone: its body never reaches a prompt to be
claimed from.
"""

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE, BriefItemSource, BriefOutcome
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.db.repositories.todos import todo_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_models import PendingBriefItemDocument
from app.services.briefing.candidates.app_names import integration_name
from app.services.todos.inbox_desk import INBOX_DESK_REF


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


async def held_candidates(
    user_id: str, held: list[PendingBriefItemDocument]
) -> list[BriefCandidate]:
    """Return each held result; the inbox desk's are Gmail findings, the rest GAIA's own work."""
    if not held:
        return []
    desk = await todo_repository.find_latest_by_external_ref(user_id, INBOX_DESK_REF)
    candidates: list[BriefCandidate] = []
    for doc in held:
        from_desk = (
            desk is not None and doc.source is BriefItemSource.TODO and doc.source_id == desk.id
        )
        first = _first_line(doc.text)
        if from_desk:
            # The desk writes each finding as one self-contained line.
            candidates.append(
                BriefCandidate(
                    source=GMAIL_INTEGRATION_ID,
                    app=integration_name(GMAIL_INTEGRATION_ID),
                    state="note",
                    title=first or doc.source_title,
                    held_id=doc.id,
                )
            )
            continue
        candidates.append(
            BriefCandidate(
                source=GAIA_SOURCE,
                app=GAIA_APP_NAME,
                state="note",
                title=f"{doc.source_title}: {first}" if first else doc.source_title,
                held_id=doc.id,
                outcome=BriefOutcome.FINISHED,
            )
        )
    return candidates
