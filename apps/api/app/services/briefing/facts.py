"""Build the facts block the model voices, and the values its slots render, from the chosen sections."""

from dataclasses import dataclass, field
from datetime import datetime

from app.constants.briefing import (
    GAIA_APP_NAME,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefBlock, SectionBlock
from app.models.briefing_models import (
    BRIEFING_ITEM_STATES,
    NEEDS_YOU_ITEM_KINDS,
    BriefingEvent,
    BriefingItem,
    BriefingSection,
    BriefingStat,
)
from app.services.briefing import context
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.candidates.calendar import event_time
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.composition.voiced_blocks import (
    block_words,
    charted_figures,
    voiced_block_lines,
)
from app.services.briefing.context import UserClock
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import (
    BriefFact,
    CountSlot,
    SlotValues,
    figures_in,
)


def _fact_line(fact_id: int, item: BriefingItem, fact: BriefFact, detail: str | None) -> str:
    line = f"- fact {fact_id} | {BRIEFING_ITEM_STATES[item.kind]}: {item.text}"
    if item.app and item.app != GAIA_APP_NAME:
        line += f" | in {item.app}"
    if fact.time:
        line += f" | time: [[fact:{fact_id}.time]] ({fact.time})"
    if detail:
        line += f" | detail: {detail}"
    if fact.count > 1:
        line += f" | [[fact:{fact_id}.count]] ({fact.count}) requests, one item"
    return line


def _work_fact_line(fact_id: int, item: BriefingItem, fact: BriefFact, art: ArtifactFact) -> str:
    line = _fact_line(fact_id, item, fact, None)
    if art.snippet:
        line += f" | summary: {art.snippet}"
    line += f" | artifact holds ~{art.chars} chars"
    if art.action:
        line += " | waiting on you"
    return line


@dataclass
class Facts:
    """The brief's sections and stats, the facts block the model voices, and what its slots render.

    deliverables maps a fact id to the todo whose deliverable it links (minted only when the
    message links it); addresses maps a fact id to the app link it carries; lead is the fact
    the composition leads with, which the message refers to, or None.
    """

    sections: list[BriefingSection]
    block: str
    values: SlotValues
    deliverables: dict[int, str]
    addresses: dict[int, str]
    lead: int | None


def work_stats(work: context.TrackedWork) -> list[BriefingStat]:
    """Build the stat row: one figure per non-empty tracked-work state, counted by subject."""
    figures = (
        (work.completed, "done since yesterday"),
        (work.running, "in progress"),
        (work.blocked, "waiting on you"),
    )
    return [
        BriefingStat(value=str(len({subject_key(d) for d in docs})), label=label)
        for docs, label in figures
        if docs
    ]


def _due_on(due_at: datetime, clock: UserClock) -> str:
    """Say a due date the way the brief does: today, or its weekday and date."""
    day = due_at.date()
    return "today" if day.isoformat() == clock.date_str else day.strftime("%a %b %-d")


def _counts(items: list[BriefingItem], open_todos: int, events: int) -> dict[CountSlot, int]:
    """Return the counts a [[count:...]] slot voices, zeros left out."""
    counts = {
        CountSlot.NEEDS_YOU: sum(1 for it in items if it.kind in NEEDS_YOU_ITEM_KINDS),
        CountSlot.DONE: sum(1 for it in items if it.kind == "lookback"),
        CountSlot.IN_PROGRESS: sum(1 for it in items if it.kind == "gaia"),
        CountSlot.WHILE_AWAY: sum(1 for it in items if it.kind == "note"),
        CountSlot.OPEN_TODOS: open_todos,
        CountSlot.EVENTS: events,
    }
    return {slot: n for slot, n in counts.items() if n}


@dataclass(frozen=True)
class CalendarSpan:
    """How the facts head the brief's calendar, and say it is empty."""

    heading: str
    empty: str


TODAY = CalendarSpan(
    heading="Today's calendar",
    empty="The user's calendar has nothing today (or no calendar is connected).",
)
WEEK_AHEAD = CalendarSpan(
    heading="The week ahead",
    empty="The user's calendar has nothing in the week ahead (or no calendar is connected).",
)


@dataclass(frozen=True)
class FactSources:
    """What the facts block is built from besides the chosen sections.

    todos_note says what the user's own todo list holds; None when the brief did not read it.
    """

    artifacts: dict[str, ArtifactFact]
    open_todos: int
    calendar: list[BriefingEvent]
    #: The pool id of each calendar event, in calendar order.
    event_ids: list[int]
    span: CalendarSpan
    todos_note: str | None
    #: The composition's blocks, whose charts, quotes, progress and notes the voice is told of.
    blocks: list[BriefBlock] = field(default_factory=list)


def build_facts(chosen: Chosen, sources: FactSources, clock: UserClock) -> Facts:
    """Assemble the facts block the model voices, and what each of its slots renders.

    Every item, signal and event is a fact numbered by its candidate id. A todo fact gives
    the model a summary, whether it is big or waiting on the user, and whether it opens a
    deliverable; app signals are voiced from their own block, with their memory.
    """
    facts: dict[int, BriefFact] = {}
    own_words = block_words(sources.blocks)
    deliverables: dict[int, str] = {}
    addresses: dict[int, str] = {}
    items = [it for sec in chosen.sections for it in sec.items]
    counts = _counts(items, sources.open_todos, len(sources.calendar))
    voiced = " · ".join(f"[[count:{slot.value}]] ({n})" for slot, n in counts.items())
    fact_lines = [f"[COUNTS] {voiced}"] if voiced else []
    for sec, picked in zip(chosen.sections, chosen.picked, strict=True):
        fact_lines.append(f"[{sec.title}]")
        for it, (fact_id, candidate) in zip(sec.items, picked, strict=True):
            art = sources.artifacts[it.todo_id] if it.todo_id is not None else None
            # An empty deliverable has nothing to open, so nothing to link.
            if art is not None and art.chars and it.todo_id is not None:
                deliverables[fact_id] = it.todo_id
            elif candidate.url:
                addresses[fact_id] = candidate.url
            facts[fact_id] = BriefFact(
                title=it.text,
                time=_due_on(candidate.due_at, clock) if candidate.due_at else None,
                count=it.count,
            )
            linkable = fact_id in deliverables or fact_id in addresses
            own_words += _own_words(candidate, it, art)
            if candidate.signal is not None:
                continue
            line = (
                _fact_line(fact_id, it, facts[fact_id], candidate.detail)
                if art is None
                else _work_fact_line(fact_id, it, facts[fact_id], art)
            )
            fact_lines.append(f"{line} | linkable" if linkable else line)
    events = list(zip(sources.event_ids, sources.calendar, strict=True))
    for fact_id, event in events:
        facts[fact_id] = BriefFact(title=event.title, time=event_time(event, clock.date_str))
    if not chosen.sections:
        fact_lines.append(
            "The brief holds no items today. Do not claim anything ran, finished, or is "
            "pending beyond what is stated here."
        )
    fact_lines += voiced_block_lines(sources.blocks)
    if sources.todos_note is not None:
        fact_lines.append(sources.todos_note)
    fact_lines.append(_calendar_note(events, sources.span, clock))
    return Facts(
        sections=chosen.sections,
        block="\n".join(fact_lines),
        values=SlotValues(
            facts=facts,
            counts=counts,
            series=charted_figures(sources.blocks),
            quoted=figures_in(own_words),
        ),
        deliverables=deliverables,
        addresses=addresses,
        lead=_lead(chosen, sources.blocks),
    )


def _lead(chosen: Chosen, blocks: list[BriefBlock]) -> int | None:
    """Return the fact id of the item the composition leads with, or None without a lead."""
    led = [b.section for b in blocks if isinstance(b, SectionBlock) and b.kind == "lead"]
    return chosen.picked[led[0]][0][0] if led else None


def _own_words(
    candidate: BriefCandidate, item: BriefingItem, art: ArtifactFact | None
) -> list[str]:
    """Return the words an item's fact line shows beside its title, which prose may quote."""
    signal = candidate.signal
    words = [candidate.title, candidate.detail, item.detail, art.snippet if art else None]
    if signal is not None:
        words += [signal.why, signal.state, signal.text]
    return [w for w in words if w]


def _event_slot(fact_id: int, time: str | None) -> str:
    return f"[[fact:{fact_id}.time]] ({time})" if time else "all day"


def _calendar_note(
    events: list[tuple[int, BriefingEvent]], span: CalendarSpan, clock: UserClock
) -> str:
    if not events:
        return span.empty
    lines = [
        f"- fact {fact_id} | {_event_slot(fact_id, event_time(e, clock.date_str))}: {e.title}"
        for fact_id, e in events
    ]
    return f"{span.heading}:\n" + "\n".join(lines)


def user_todos_note(open_count: int, open_titles: list[str]) -> str:
    if not open_count:
        return "The user's own todo list is empty."
    first_few = f" (first few: {'; '.join(open_titles)})" if open_titles else ""
    return (
        f"The user's own open todos{first_few} are counted in [COUNTS]"
        "; never voice that list as clear or empty."
    )
