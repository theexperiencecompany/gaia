"""Choose the daily brief's sections from every candidate in one structured call.

The judge returns the lead (with what GAIA offers to do), the needs-you, updates and
GAIA's-work lists in order, each chosen candidate worded as a short title and detail,
and what it dropped. Code holds it to the contract: an unknown, repeated or missing id,
an event outside the lead, a lead with no offer, or wording outside the brief item's
shape is sent back once with the problem named, then fails the brief. The lead is never
also filed in a section, and a list longer than its section's cap keeps its first items.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.brief_selection_prompts import BRIEF_SELECTION_PROMPT
from app.constants.briefing import (
    ACTION_SECTIONS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_SELECTION_LABEL,
    MAX_SELECTION_ATTEMPTS,
    SECTION_CAPS,
    BriefAction,
    BriefOutcome,
    SectionKey,
)
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.briefing_models import NEEDS_YOU_ITEM_KINDS, BriefingItem, BriefingItemKind
from app.models.scout_models import SignalImportance
from app.utils.errors import AppError
from shared.py.wide_events import log

CandidatePool = Mapping[int, BriefCandidate]


class ChosenItem(BaseModel):
    """One chosen candidate, worded for the brief from that candidate's own facts."""

    id: int
    action: BriefAction | None = Field(
        default=None, description="lead and needs_you only: what the user does about it"
    )
    outcome: BriefOutcome | None = Field(
        default=None, description="updates and gaia_did only: where it got to"
    )
    title: str = Field(
        description=f"A noun phrase of at most {BRIEF_ITEM_TITLE_MAX_CHARS} characters, never a sentence"
    )
    detail: str | None = Field(
        default=None,
        description=f"One line of at most {BRIEF_ITEM_DETAIL_MAX_CHARS} characters, or null",
    )


class BriefSelectionAnswer(BaseModel):
    """The judge's answer: chosen candidates per section, most important first."""

    lead: ChosenItem | None = Field(
        default=None, description="The one to start the day on, or null"
    )
    offer: str | None = Field(
        default=None, description="What GAIA will do for the lead, one short sentence"
    )
    needs_you: list[ChosenItem] = Field(default_factory=list)
    updates: list[ChosenItem] = Field(default_factory=list)
    gaia_did: list[ChosenItem] = Field(default_factory=list)
    dropped: list[int] = Field(default_factory=list)


@dataclass(frozen=True)
class BriefSelection:
    """The checked selection: ids per section in reading order, their items, and what was left out.

    more counts, per section, what the judge chose past its cap; those wait for a later brief.
    """

    sections: dict[SectionKey, list[int]]
    items: dict[int, BriefingItem]
    offer: str | None
    dropped: list[int]
    more: dict[SectionKey, int]


EMPTY_SELECTION = BriefSelection(sections={}, items={}, offer=None, dropped=[], more={})


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
    if candidate.action is not None:
        parts.append(f"action {candidate.action.value}")
    if candidate.outcome is not None:
        parts.append(f"outcome {candidate.outcome.value}")
    return " | ".join(parts)


def _rejected(problem: str, answer: BriefSelectionAnswer) -> AppError:
    return AppError(
        message="the brief's selection judge broke its contract",
        why=problem,
        fix="the judge was asked again once with the problem named; the next scheduled brief retries",
        meta={"answer": answer.model_dump()},
    )


def _item_kind(key: SectionKey, candidate: BriefCandidate) -> BriefingItemKind:
    """How a kept candidate reads: its own state, unless its section says it waits on the user or not."""
    if key is SectionKey.NEEDS_YOU and candidate.state not in NEEDS_YOU_ITEM_KINDS:
        return "you"
    if key in (SectionKey.UPDATES, SectionKey.GAIA_DID) and candidate.state in NEEDS_YOU_ITEM_KINDS:
        return "note"
    return candidate.state


def _item(
    key: SectionKey, chosen: ChosenItem, candidate: BriefCandidate, offer: str | None
) -> BriefingItem:
    """Word a kept candidate as its section's item; what its producer knows beats the judge's word."""
    asks = key in ACTION_SECTIONS
    return BriefingItem(
        text=chosen.title.strip(),
        detail=(chosen.detail or "").strip() or None,
        action=(candidate.action or chosen.action) if asks else None,
        outcome=None if asks else (candidate.outcome or chosen.outcome),
        todo_id=candidate.todo_id,
        kind=_item_kind(key, candidate),
        count=candidate.count,
        app=candidate.app,
        url=candidate.url,
        people=list(candidate.people),
        offer=offer if key is SectionKey.LEAD else None,
    )


def _wording_problems(key: SectionKey, chosen: ChosenItem, candidate: BriefCandidate) -> list[str]:
    """Name where the judge's wording breaks the brief item's shape, so its retry can fix it."""
    where = f"id {chosen.id} in {key.value}"
    title = chosen.title.strip()
    problems = []
    if not title or len(title) > BRIEF_ITEM_TITLE_MAX_CHARS:
        problems.append(
            f"{where}: a title of {len(title)} characters, not 1 to {BRIEF_ITEM_TITLE_MAX_CHARS}"
        )
    detail = (chosen.detail or "").strip()
    if len(detail) > BRIEF_ITEM_DETAIL_MAX_CHARS:
        problems.append(
            f"{where}: a detail of {len(detail)} characters, over {BRIEF_ITEM_DETAIL_MAX_CHARS}"
        )
    if key in ACTION_SECTIONS and (candidate.action or chosen.action) is None:
        problems.append(f"{where}: no action")
    if key not in ACTION_SECTIONS and (candidate.outcome or chosen.outcome) is None:
        problems.append(f"{where}: no outcome")
    return problems


def _items(
    kept: Mapping[SectionKey, list[ChosenItem]],
    pool: CandidatePool,
    offer: str | None,
    answer: BriefSelectionAnswer,
) -> dict[int, BriefingItem]:
    problems = [
        problem
        for key, entries in kept.items()
        for chosen in entries
        for problem in _wording_problems(key, chosen, pool[chosen.id])
    ]
    if problems:
        raise _rejected("; ".join(problems), answer)
    return {
        chosen.id: _item(key, chosen, pool[chosen.id], offer)
        for key, entries in kept.items()
        for chosen in entries
    }


def checked_selection(answer: BriefSelectionAnswer, pool: CandidatePool) -> BriefSelection:
    """Hold the judge's answer to the contract and the section caps; raise AppError when it breaks it."""
    lead = [answer.lead] if answer.lead is not None else []
    lead_ids = {c.id for c in lead}
    lists: dict[SectionKey, list[ChosenItem]] = {
        SectionKey.LEAD: lead,
        SectionKey.NEEDS_YOU: [c for c in answer.needs_you if c.id not in lead_ids],
        SectionKey.UPDATES: [c for c in answer.updates if c.id not in lead_ids],
        SectionKey.GAIA_DID: [c for c in answer.gaia_did if c.id not in lead_ids],
    }
    filed = [c.id for key, entries in lists.items() if key is not SectionKey.LEAD for c in entries]
    placed = [*lead_ids, *filed, *answer.dropped]
    unknown = sorted(set(placed) - set(pool))
    if unknown:
        raise _rejected(f"unknown id(s) {unknown}", answer)
    repeated = sorted({i for i in placed if placed.count(i) > 1})
    if repeated:
        raise _rejected(f"id(s) {repeated} placed more than once", answer)
    events = {i for i, c in pool.items() if c.kind is CandidateKind.EVENT}
    misfiled = sorted(set(filed) & events)
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
    kept = {key: entries[: SECTION_CAPS[key]] for key, entries in lists.items() if entries}
    return BriefSelection(
        sections={key: [c.id for c in entries] for key, entries in kept.items()},
        items=_items(kept, pool, offer, answer),
        offer=offer,
        dropped=list(answer.dropped),
        more={
            key: len(entries) - SECTION_CAPS[key]
            for key, entries in lists.items()
            if len(entries) > SECTION_CAPS[key]
        },
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
        title_max=BRIEF_ITEM_TITLE_MAX_CHARS,
        detail_max=BRIEF_ITEM_DETAIL_MAX_CHARS,
        actions=", ".join(BriefAction),
        outcomes=", ".join(BriefOutcome),
    )
    note = ""
    for _ in range(MAX_SELECTION_ATTEMPTS - 1):
        try:
            return checked_selection(await _ask(user_id, prompt, note), pool)
        except AppError as exc:
            log.warning("briefing.selection_rejected", problem=exc.why)
            note = f"Your last answer was rejected: {exc.why}. Answer again, fixing that."
    return checked_selection(await _ask(user_id, prompt, note), pool)
