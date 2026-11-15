"""Build the facts block the model voices, and the values its slots render, from the chosen sections."""

from dataclasses import dataclass, field
from datetime import date
from itertools import groupby

from app.constants.briefing import (
    CALENDAR_UNAVAILABLE,
    GAIA_APP_NAME,
    NO_CALENDAR_CONNECTED,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefBlock, SectionBlock
from app.models.brief_pool_models import DataSeries, GoalState
from app.models.briefing_models import (
    NEEDS_YOU_ITEM_KINDS,
    BriefingEvent,
    BriefingItem,
    BriefingSection,
    BriefingStat,
    UnreadSource,
)
from app.services.briefing import context
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.candidates.calendar import event_detail, start_time
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.composition.voiced_blocks import (
    block_words,
    charted_figures,
    voiced_block_lines,
)
from app.services.briefing.context import CalendarGap, CalendarUnread, UserClock, due_on
from app.services.briefing.fact_pool.render import (
    ON_ONE_SUBJECT,
    goal_progress,
    item_state,
    repeat_note,
    unread_note,
)
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import (
    BriefFact,
    CountSlot,
    SeriesField,
    SlotValues,
    figures_in,
    series_figures,
)


def _fact_line(
    fact_id: int, item: BriefingItem, fact: BriefFact, candidate: BriefCandidate, clock: UserClock
) -> str:
    said = item_state(candidate)
    state = said[:1].upper() + said[1:]
    line = f"- fact {fact_id} | {state}: {item.text}"
    if item.app and item.app != GAIA_APP_NAME:
        line += f" | in {item.app}"
    if candidate.standing is not None:
        line += f" | stands: {candidate.standing}"
    if fact.time:
        line += f" | time: [[fact:{fact_id}.time]] ({fact.time})"
    if candidate.detail:
        line += f" | detail: {candidate.detail}"
    if fact.count > 1:
        line += f" | [[fact:{fact_id}.count]] ({fact.count}) {ON_ONE_SUBJECT}"
    if (repeat := repeat_note(candidate, clock)) is not None:
        line += f" | {repeat}"
    return line


def _work_fact_line(
    fact_id: int,
    item: BriefingItem,
    fact: BriefFact,
    candidate: BriefCandidate,
    art: ArtifactFact,
    clock: UserClock,
) -> str:
    line = _fact_line(fact_id, item, fact, candidate, clock)
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
    """Build the stat row: one figure per non-empty tracked-work state, each subject once, in full."""
    figures = (
        (len({subject_key(d) for d in work.completed}), "done since last brief"),
        (work.open_subjects.running, "in progress"),
        (work.open_subjects.blocked, "waiting on you"),
    )
    return [BriefingStat(value=str(n), label=label) for n, label in figures if n]


@dataclass(frozen=True)
class BriefSpan:
    """How the facts name the brief's span: its calendar's heading, an empty calendar, no items.

    days is how many local days the calendar covers; a span of several lists it under each
    day's heading, with its count.
    """

    heading: str
    empty: str
    no_items: str
    days: int = 1


_NO_CLAIM = "Do not claim anything ran, finished, or is pending beyond what is stated here."
TODAY = BriefSpan(
    heading="Today's calendar",
    empty="The user's calendar has nothing today.",
    no_items=f"No tracked work, results or app items need them today. {_NO_CLAIM}",
)
WEEK_AHEAD = BriefSpan(
    heading="The week ahead",
    empty="The user's calendar has nothing in the week ahead.",
    no_items=f"The digest holds no items from this week. {_NO_CLAIM}",
    days=7,
)


@dataclass(frozen=True)
class WeekRecap:
    """The week as code counts it: each series' total, grouped by what it counts, and each goal."""

    series: list[DataSeries]
    goals: list[GoalState]


@dataclass(frozen=True)
class FactSources:
    """What the facts block is built from besides the chosen sections.

    todos_note says what the user's own todo list holds; None when the brief did not read it.
    """

    #: GAIA's tracked work by todo id; the user's own todos have no deliverable here.
    artifacts: dict[str, ArtifactFact]
    open_todos: int
    #: The span's events, or why its calendar went unread: never an empty day.
    calendar: list[BriefingEvent] | CalendarUnread
    #: The pool id of each calendar event, in calendar order.
    event_ids: list[int]
    span: BriefSpan
    todos_note: str | None
    #: The composition's blocks, whose charts, quotes, progress and notes the voice is told of.
    blocks: list[BriefBlock] = field(default_factory=list)
    #: The user's own open todos past their due date, however many: counted, never listed.
    overdue_todos: int = 0
    #: GAIA's open tracked work, each subject once.
    open_tracked: int = 0
    #: The weekly's recap of the week: what each count series totals and how each goal moved.
    recap: WeekRecap | None = None
    #: The connected apps that went unread, the calendar aside: never empty, only unknown.
    unread: list[UnreadSource] = field(default_factory=list)


def _counts(
    placed: list[tuple[BriefingItem, BriefCandidate]], sources: FactSources, events: int
) -> dict[CountSlot, int]:
    """Return the counts a [[count:...]] slot voices, each counting only what its name claims, zeros left out.

    Waiting on you leaves out a calendar event and backlog; while away is what came in to be
    held for the brief.
    """
    counts = {
        CountSlot.NEEDS_YOU: sum(
            1
            for it, c in placed
            if it.kind in NEEDS_YOU_ITEM_KINDS and not (c.is_event or c.backlog)
        ),
        CountSlot.DONE: sum(1 for it, _ in placed if it.kind == "lookback"),
        CountSlot.IN_PROGRESS: sum(1 for it, _ in placed if it.kind == "gaia"),
        CountSlot.WHILE_AWAY: sum(1 for _, c in placed if c.held_id is not None),
        CountSlot.OPEN_TODOS: sources.open_todos,
        CountSlot.OVERDUE_TODOS: sources.overdue_todos,
        CountSlot.OPEN_TRACKED: sources.open_tracked,
        CountSlot.EVENTS: events,
    }
    return {slot: n for slot, n in counts.items() if n}


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
    placed: list[tuple[BriefingItem, BriefCandidate]] = []
    fact_lines: list[str] = []
    for sec, picked in zip(chosen.sections, chosen.picked, strict=True):
        fact_lines.append(f"[{sec.title}]")
        for it, (fact_id, candidate) in zip(sec.items, picked, strict=True):
            art = sources.artifacts.get(it.todo_id) if it.todo_id is not None else None
            # An empty deliverable has nothing to open, so nothing to link.
            if art is not None and art.chars and it.todo_id is not None:
                deliverables[fact_id] = it.todo_id
            elif candidate.url:
                addresses[fact_id] = candidate.url
            words = _own_words(candidate, it, art)
            facts[fact_id] = BriefFact(
                title=it.text,
                time=due_on(candidate.due_at, clock) if candidate.due_at else None,
                count=it.count,
                kind=it.kind,
                words=" ".join(words),
            )
            linkable = fact_id in deliverables or fact_id in addresses
            own_words += words
            placed.append((it, candidate))
            if candidate.signal is not None:
                continue
            line = (
                _fact_line(fact_id, it, facts[fact_id], candidate, clock)
                if art is None
                else _work_fact_line(fact_id, it, facts[fact_id], candidate, art, clock)
            )
            fact_lines.append(f"{line} | linkable" if linkable else line)
    calendar = sources.calendar if isinstance(sources.calendar, list) else []
    counts = _counts(placed, sources, len(calendar))
    voiced = " · ".join(f"[[count:{slot.value}]] ({n})" for slot, n in counts.items())
    if voiced:
        fact_lines.insert(0, f"[COUNTS] {voiced}")
    events = list(zip(sources.event_ids, calendar, strict=True))
    for fact_id, event in events:
        facts[fact_id] = BriefFact(title=event.title, time=start_time(event))
    fact_lines += _closing_lines(chosen, sources, events)
    if sources.recap is not None:
        own_words += [title for goal in sources.recap.goals for title in goal.linked]
    return Facts(
        sections=chosen.sections,
        block="\n".join(fact_lines),
        values=SlotValues(
            facts=facts,
            counts=counts,
            series={
                **charted_figures(sources.blocks),
                **{
                    series.id: series_figures(series)
                    for series in (sources.recap.series if sources.recap else [])
                },
            },
            quoted=figures_in(own_words),
        ),
        deliverables=deliverables,
        addresses=addresses,
        lead=_lead(chosen, sources.blocks),
    )


def _closing_lines(
    chosen: Chosen, sources: FactSources, events: list[tuple[int, BriefingEvent]]
) -> list[str]:
    """Return what follows the items: an empty day, what went unread, the blocks, the recap, todos, the calendar."""
    lines = [sources.span.no_items] if not chosen.sections else []
    if (unread := unread_note(sources.unread)) is not None:
        lines.append(unread)
    lines += voiced_block_lines(sources.blocks)
    if sources.recap is not None:
        lines += _recap_lines(sources.recap)
    if sources.todos_note is not None:
        lines.append(sources.todos_note)
    return [*lines, _calendar_note(events, sources)]


def _lead(chosen: Chosen, blocks: list[BriefBlock]) -> int | None:
    """Return the fact id of the item the composition leads with, or None without a lead."""
    led = [b.section for b in blocks if isinstance(b, SectionBlock) and b.kind == "lead"]
    return chosen.picked[led[0]][0][0] if led else None


def _own_words(
    candidate: BriefCandidate, item: BriefingItem, art: ArtifactFact | None
) -> list[str]:
    """Return the words an item's fact line shows beside its title, which prose may quote."""
    signal = candidate.signal
    words = [
        candidate.title,
        candidate.standing,
        candidate.detail,
        item.detail,
        art.snippet if art else None,
    ]
    if signal is not None:
        words += [signal.why, signal.state, signal.text]
    return [w for w in words if w]


def _event_slot(fact_id: int, time: str | None) -> str:
    return f"[[fact:{fact_id}.time]] ({time})" if time else "all day"


def _event_lines(events: list[tuple[int, BriefingEvent]]) -> list[str]:
    return [
        f"- fact {fact_id} | {_event_slot(fact_id, start_time(e))}: {e.title}"
        + (f" | {detail}" if (detail := event_detail(e)) else "")
        for fact_id, e in events
    ]


def _by_day(events: list[tuple[int, BriefingEvent]]) -> list[str]:
    """List the events under each day's heading and count, naming the busiest days.

    A day is the busiest only beside a lighter day that has events: equal days have none.
    """
    days = {day: list(group) for day, group in groupby(events, key=lambda pair: pair[1].date)}
    counts = [len(group) for group in days.values()]
    busiest = max(counts) if max(counts) > min(counts) else None
    lines: list[str] = []
    for day, group in days.items():
        busy = ", the week's busiest" if len(group) == busiest else ""
        label = date.fromisoformat(day).strftime("%A %b %-d")
        lines += [f"{label}, {len(group)} event(s){busy}:", *_event_lines(group)]
    return lines


def _calendar_note(events: list[tuple[int, BriefingEvent]], sources: FactSources) -> str:
    if isinstance(sources.calendar, CalendarUnread):
        if sources.calendar.gap is CalendarGap.UNAVAILABLE:
            return CALENDAR_UNAVAILABLE
        return NO_CALENDAR_CONNECTED
    if not events:
        return sources.span.empty
    if sources.span.days > 1:
        return "\n".join(
            [
                f"{sources.span.heading}, {len(events)} event(s):",
                *_by_day(events),
            ]
        )
    return f"{sources.span.heading}:\n" + "\n".join(_event_lines(events))


def _recap_lines(recap: WeekRecap) -> list[str]:
    """Say the week's totals as one grouped recap, and what moved and what stuck on each goal."""
    lines: list[str] = []
    if recap.series:
        lines.append(
            "[THE WEEK IN NUMBERS] (voice these as one grouped recap of the week, never as a list)"
        )
        lines += [
            f"- {s.label}: [[series:{s.id}.total]] ({series_figures(s)[SeriesField.TOTAL]}"
            f"{f' {s.unit}' if s.unit else ''})"
            for s in recap.series
        ]
    if recap.goals:
        lines.append("[GOALS THIS WEEK]")
        lines += [_goal_week_line(goal) for goal in recap.goals]
    return lines


def _goal_week_line(goal: GoalState) -> str:
    done = goal.linked[: goal.done]
    moved = (
        f"moved forward, {goal_progress(goal)}: {'; '.join(done)}"
        if done
        else f"nothing linked to it finished, {goal_progress(goal)}"
    )
    line = f'- "{goal.statement}": {moved}'
    if goal.stalled:
        line += f" | stuck a week or more: {'; '.join(goal.stalled)}"
    return line


def user_todos_note(open_count: int, overdue: int = 0, tracked_open: int = 0) -> str:
    """Say what the user's todo list holds: their own todos, and beside them GAIA's open tracked ones."""
    tracked = (
        f" GAIA's tracked work holds [[count:{CountSlot.OPEN_TRACKED.value}]] open beside them."
        if tracked_open
        else ""
    )
    if not open_count:
        if tracked_open:
            return (
                "The user has no todos of their own outside GAIA's tracked work, which holds "
                f"[[count:{CountSlot.OPEN_TRACKED.value}]] open: never call their todo list "
                "empty or clear."
            )
        return "The user's own todo list is empty."
    note = (
        "The user's own open todos are counted in [COUNTS]"
        "; never voice that list as clear or empty."
    )
    if overdue:
        note += (
            " [[count:overdue_todos]] of them are past due: say that count in one plain line,"
            " never list them."
        )
    return note + tracked
