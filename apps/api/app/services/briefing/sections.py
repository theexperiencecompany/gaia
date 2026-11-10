"""Lay the judge's selection out as the brief's sections, and read back what it kept."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.constants.briefing import (
    SECTION_NUMERALS,
    SECTION_ORDER,
    SectionKey,
)
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.briefing_models import (
    NEEDS_YOU_ITEM_KINDS,
    BriefingItem,
    BriefingItemKind,
    BriefingSection,
)
from app.models.scout_models import RememberedSignal
from app.services.briefing.candidates.judge import BriefSelection, CandidatePool
from shared.py.wide_events import log


@dataclass(frozen=True)
class Chosen:
    """The brief's sections, each item beside the pool id and candidate it came from, in order."""

    sections: list[BriefingSection]
    picked: list[list[tuple[int, BriefCandidate]]]


def _item_kind(key: SectionKey, candidate: BriefCandidate) -> BriefingItemKind:
    """How a kept candidate reads: its own state, unless its section says it waits on the user or not."""
    if key is SectionKey.NEEDS_YOU and candidate.state not in NEEDS_YOU_ITEM_KINDS:
        return "you"
    if key in (SectionKey.UPDATES, SectionKey.GAIA_DID) and candidate.state in NEEDS_YOU_ITEM_KINDS:
        return "note"
    return candidate.state


def _item(key: SectionKey, candidate: BriefCandidate, offer: str | None) -> BriefingItem:
    return BriefingItem(
        text=candidate.title,
        todo_id=candidate.todo_id,
        kind=_item_kind(key, candidate),
        count=candidate.count,
        app=candidate.app,
        url=candidate.url,
        people=list(candidate.people),
        offer=offer if key is SectionKey.LEAD else None,
    )


def chosen_sections(
    selection: BriefSelection, pool: CandidatePool, titles: Mapping[SectionKey, str]
) -> Chosen:
    """Lay the judge's selection out as the brief's sections, in reading order, empty ones left out."""
    filled = [
        (key, [(i, pool[i]) for i in selection.sections[key]])
        for key in SECTION_ORDER
        if selection.sections.get(key)
    ]
    return Chosen(
        sections=[
            BriefingSection(
                numeral=SECTION_NUMERALS[n],
                title=titles[key],
                key=key,
                items=[_item(key, c, selection.offer) for _, c in picked],
            )
            for n, (key, picked) in enumerate(filled)
        ],
        picked=[picked for _, picked in filled],
    )


def carried_ids(selection: BriefSelection, pool: CandidatePool, duplicates: list[str]) -> list[str]:
    """Return the held results this brief accounts for: kept, dropped by the judge, or said twice.

    A held result the section caps left out waits for the next brief.
    """
    accounted = [i for ids in selection.sections.values() for i in ids] + selection.dropped
    return [held for i in accounted if (held := pool[i].held_id) is not None] + duplicates


def chosen_signals(
    chosen: Chosen, remembered: list[RememberedSignal]
) -> list[tuple[int, RememberedSignal]]:
    """Return the app signals the judge kept, by fact id, with their memory for the apps block."""
    by_key = {(r.signal.integration_id, r.signal.external_id): r for r in remembered}
    return [
        (fact_id, by_key[(c.signal.integration_id, c.signal.external_id)])
        for picked in chosen.picked
        for fact_id, c in picked
        if c.signal is not None
    ]


def log_selection(candidates: int, selection: BriefSelection) -> None:
    log.set_ns(
        "brief_selection",
        candidates=candidates,
        kept={key.value: len(ids) for key, ids in selection.sections.items()},
        dropped=len(selection.dropped),
        capped=len(selection.capped),
    )


def event_ids(pool: CandidatePool) -> list[int]:
    """Return the pool id of each calendar event, in calendar order."""
    return [i for i, c in pool.items() if c.kind is CandidateKind.EVENT]
