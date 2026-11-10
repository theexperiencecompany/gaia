"""Choose the daily brief's sections from every candidate in one structured call.

The judge returns the lead (with what GAIA offers to do), the needs-you, updates and
GAIA's-work lists in order, and what it dropped. Code holds it to the contract: an
unknown, repeated or missing id, an event outside the lead, or a lead with no offer is
sent back once with the problem named, then fails the brief; a list longer than its
section's cap keeps its first items.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.brief_selection_prompts import BRIEF_SELECTION_PROMPT
from app.constants.briefing import (
    BRIEF_SELECTION_LABEL,
    MAX_SELECTION_ATTEMPTS,
    SECTION_CAPS,
    SectionKey,
)
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.scout_models import SignalImportance
from app.utils.errors import AppError
from shared.py.wide_events import log

CandidatePool = Mapping[int, BriefCandidate]


class BriefSelectionAnswer(BaseModel):
    """The judge's answer: candidate ids per section, most important first."""

    lead: int | None = Field(default=None, description="The one id to start the day on, or null")
    offer: str | None = Field(
        default=None, description="What GAIA will do for the lead, one short sentence"
    )
    needs_you: list[int] = Field(default_factory=list)
    updates: list[int] = Field(default_factory=list)
    gaia_did: list[int] = Field(default_factory=list)
    dropped: list[int] = Field(default_factory=list)


@dataclass(frozen=True)
class BriefSelection:
    """The checked selection: ids per section in reading order, and what was left out.

    capped are ids the judge kept past a section's cap; they wait for a later brief.
    """

    sections: dict[SectionKey, list[int]]
    offer: str | None
    dropped: list[int]
    capped: list[int]


EMPTY_SELECTION = BriefSelection(sections={}, offer=None, dropped=[], capped=[])


def _line(candidate_id: int, candidate: BriefCandidate) -> str:
    head = f"{candidate_id}. [{candidate.app}] {candidate.kind.value}"
    if candidate.importance is SignalImportance.HIGH:
        head += ", important"
    parts = [f"{head}: {candidate.title}"]
    if candidate.detail:
        parts.append(candidate.detail)
    if candidate.due_at is not None:
        parts.append(f"due {candidate.due_at.date().isoformat()}")
    if candidate.people:
        parts.append(f"with {', '.join(candidate.people)}")
    if candidate.count > 1:
        parts.append(f"{candidate.count} requests, one item")
    return " | ".join(parts)


def _rejected(problem: str, answer: BriefSelectionAnswer) -> AppError:
    return AppError(
        message="the brief's selection judge broke its contract",
        why=problem,
        fix="the judge was asked again once with the problem named; the next scheduled brief retries",
        meta={"answer": answer.model_dump()},
    )


def checked_selection(answer: BriefSelectionAnswer, pool: CandidatePool) -> BriefSelection:
    """Hold the judge's answer to the contract and the section caps; raise AppError when it breaks it."""
    lead = [answer.lead] if answer.lead is not None else []
    lists: dict[SectionKey, list[int]] = {
        SectionKey.LEAD: lead,
        SectionKey.NEEDS_YOU: answer.needs_you,
        SectionKey.UPDATES: answer.updates,
        SectionKey.GAIA_DID: answer.gaia_did,
    }
    placed = [*lead, *answer.needs_you, *answer.updates, *answer.gaia_did, *answer.dropped]
    unknown = sorted(set(placed) - set(pool))
    if unknown:
        raise _rejected(f"unknown id(s) {unknown}", answer)
    repeated = sorted({i for i in placed if placed.count(i) > 1})
    if repeated:
        raise _rejected(f"id(s) {repeated} placed more than once", answer)
    events = {i for i, c in pool.items() if c.kind is CandidateKind.EVENT}
    misfiled = sorted(set(answer.needs_you + answer.updates + answer.gaia_did) & events)
    if misfiled:
        raise _rejected(f"event id(s) {misfiled} filed outside the lead", answer)
    missing = sorted(set(pool) - events - set(placed))
    if missing:
        raise _rejected(f"id(s) {missing} not placed in any list", answer)
    offer = (answer.offer or "").strip() or None
    if lead and offer is None:
        raise _rejected("a lead with no offer", answer)
    if not lead and offer is not None:
        raise _rejected("an offer with no lead", answer)
    capped = [i for key, ids in lists.items() for i in ids[SECTION_CAPS[key] :]]
    return BriefSelection(
        sections={key: ids[: SECTION_CAPS[key]] for key, ids in lists.items() if ids},
        offer=offer,
        dropped=list(answer.dropped),
        capped=capped,
    )


async def _ask(user_id: str, prompt: str, note: str) -> BriefSelectionAnswer:
    return await ainvoke_structured(
        BriefSelectionAnswer,
        f"{prompt}\n{note}" if note else prompt,
        label=BRIEF_SELECTION_LABEL,
        config=metered_config(user_id),
    )


async def select_candidates(
    user_id: str,
    pool: CandidatePool,
    criteria: Mapping[str, str],
    now: datetime,
    timezone: str,
) -> BriefSelection:
    """Choose the brief's sections from the pool; a pool with nothing but events needs no call.

    criteria maps an app's display name to how its scout tells what needs this user.
    """
    if all(c.kind is CandidateKind.EVENT for c in pool.values()):
        return EMPTY_SELECTION
    prompt = BRIEF_SELECTION_PROMPT.format(
        today=now.date().isoformat(),
        timezone=timezone,
        criteria="\n".join(f"- {app}: {text}" for app, text in criteria.items())
        or "- (no app wrote criteria)",
        items="\n".join(_line(i, c) for i, c in pool.items()),
        needs_you_cap=SECTION_CAPS[SectionKey.NEEDS_YOU],
        updates_cap=SECTION_CAPS[SectionKey.UPDATES],
        gaia_did_cap=SECTION_CAPS[SectionKey.GAIA_DID],
    )
    note = ""
    for _ in range(MAX_SELECTION_ATTEMPTS - 1):
        try:
            return checked_selection(await _ask(user_id, prompt, note), pool)
        except AppError as exc:
            log.warning("briefing.selection_rejected", problem=exc.why)
            note = f"Your last answer was rejected: {exc.why}. Answer again, fixing that."
    return checked_selection(await _ask(user_id, prompt, note), pool)
