"""Build the facts block the model voices, and the values its slots render, from the chosen sections."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import groupby

from app.agents.prompts.brief_fact_prompts import (
    CALENDAR_UNAVAILABLE,
    COUNTS_HEADER,
    GOALS_THIS_WEEK_HEADER,
    NO_CALENDAR_CONNECTED,
    ONLY_TRACKED_TODOS,
    OWN_TODOS_COUNTED,
    OWN_TODOS_EMPTY,
    OWN_TODOS_OVERDUE,
    SHOWN_NOT_TOTAL,
    SIGNALS_HEADER,
    TODAY_EMPTY,
    TODAY_HEADING,
    TODAY_NO_ITEMS,
    TODAY_SPAN,
    TRACKED_BESIDE_OWN,
    WEEK_AHEAD_EMPTY,
    WEEK_AHEAD_HEADING,
    WEEK_AHEAD_NO_ITEMS,
    WEEK_AHEAD_SPAN,
    WEEK_IN_NUMBERS_HEADER,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefBlock, SectionBlock
from app.models.brief_item_models import GroupState
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingSection,
    BriefingStat,
    UnreadSource,
)
from app.models.brief_pool_models import DataSeries, GoalState
from app.models.brief_slot_models import (
    CountName,
    CountSlot,
    SeriesField,
    SeriesSlot,
)
from app.models.scout_models import SignalImportance
from app.services.briefing.artifacts import ArtifactFact
from app.services.briefing.calendar_read import CalendarGap, CalendarRead
from app.services.briefing.candidates.calendar import start_time
from app.services.briefing.candidates.subjects import subject_key
from app.services.briefing.clock import DayWindow, UserClock
from app.services.briefing.composition.voiced_blocks import (
    block_words,
    charted_figures,
    voiced_block_lines,
)
from app.services.briefing.fact_pool.render import (
    Voiced,
    goal_progress,
    item_line,
    unread_note,
)
from app.services.briefing.formats import day
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import (
    BriefFact,
    SlotValues,
    candidate_fact,
    figures_in,
    series_figures,
)
from app.services.briefing.work import TrackedWork


@dataclass
class Facts:
    """The brief's sections and stats, the facts block the model voices, and what its slots render.

    deliverables maps a fact id to the todo whose deliverable it links (minted only when the
    message links it); addresses maps a fact id to the app link it carries; lead is the fact
    the composition leads with, which the message refers to, or None.
    """

    sections: list[BriefingSection]
    block: str
    #: The app signals the brief placed, grouped per app, as the voice reads them; "" for none.
    signals: str
    values: SlotValues
    deliverables: dict[int, str]
    addresses: dict[int, str]
    lead: int | None


def work_stats(work: TrackedWork) -> list[BriefingStat]:
    """Build the stat row: one figure per non-empty tracked-work state, each subject once, in full."""
    figures = (
        (len({subject_key(d) for d in work.completed}), "done since last brief"),
        (work.open_subjects.running, "in progress"),
        (work.open_subjects.blocked, "waiting on you"),
    )
    return [BriefingStat(value=str(n), label=label) for n, label in figures if n]


@dataclass(frozen=True)
class BriefSpan:
    """The days a brief's calendar and what falls due cover, and how its facts name them.

    It starts starts_in days from today and covers days local days; a span of several lists
    its calendar under each day's heading, with its count. words names it in the pool context.
    """

    heading: str
    empty: str
    no_items: str
    words: str
    starts_in: int = 0
    days: int = 1

    def window(self, clock: UserClock) -> DayWindow:
        return clock.days(clock.today + timedelta(days=self.starts_in), self.days)


TODAY = BriefSpan(
    heading=TODAY_HEADING, empty=TODAY_EMPTY, no_items=TODAY_NO_ITEMS, words=TODAY_SPAN
)
WEEK_AHEAD = BriefSpan(
    heading=WEEK_AHEAD_HEADING,
    empty=WEEK_AHEAD_EMPTY,
    no_items=WEEK_AHEAD_NO_ITEMS,
    words=WEEK_AHEAD_SPAN,
    starts_in=1,
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
    #: The calendar's read: the span's events, or why it went unread (never an empty day).
    calendar: CalendarRead
    #: The pool's calendar events by id, in calendar order.
    event_items: dict[int, BriefCandidate]
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
) -> dict[CountName, int]:
    """Return the counts a count slot voices, each counting only what its name claims, zeros left out.

    Waiting on you leaves out a calendar event and backlog; while away is what came in to be
    held for the brief.
    """
    counts = {
        CountName.NEEDS_YOU: sum(
            1 for it, c in placed if it.kind.needs_you and not (c.is_event or c.backlog)
        ),
        CountName.DONE: sum(1 for it, _ in placed if it.kind.group is GroupState.DONE),
        CountName.IN_PROGRESS: sum(
            1 for it, _ in placed if it.kind.group is GroupState.IN_PROGRESS
        ),
        CountName.WHILE_AWAY: sum(1 for _, c in placed if c.held_id is not None),
        CountName.OPEN_TODOS: sources.open_todos,
        CountName.OVERDUE_TODOS: sources.overdue_todos,
        CountName.OPEN_TRACKED: sources.open_tracked,
        CountName.EVENTS: events,
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
    signals: list[tuple[int, BriefCandidate]] = []
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
            facts[fact_id] = candidate_fact(
                candidate, clock, title=it.text, kind=it.kind, words=" ".join(words)
            )
            own_words += words
            placed.append((it, candidate))
            if candidate.signal is not None:
                signals.append((fact_id, candidate))
                continue
            linkable = fact_id in deliverables or fact_id in addresses
            fact_lines.append(
                item_line(fact_id, candidate, clock, Voiced(facts[fact_id], linkable, art))
            )
    calendar = sources.calendar.events
    counts = _counts(placed, sources, len(calendar))
    voiced = " · ".join(f"{CountSlot(name)} ({n})" for name, n in counts.items())
    if voiced:
        fact_lines.insert(0, f"{COUNTS_HEADER} {voiced}")
    events = list(zip(sources.event_items, calendar, strict=True))
    for fact_id, event in events:
        facts[fact_id] = BriefFact(title=event.title, time=start_time(event))
    fact_lines += _closing_lines(chosen, sources, events, facts, clock)
    if sources.recap is not None:
        own_words += [title for goal in sources.recap.goals for title in goal.linked]
    return Facts(
        sections=chosen.sections,
        block="\n".join(fact_lines),
        signals=_signals_block(signals, facts, addresses, clock),
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
    chosen: Chosen,
    sources: FactSources,
    events: list[tuple[int, BriefingEvent]],
    facts: dict[int, BriefFact],
    clock: UserClock,
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
    return [*lines, _calendar_note(events, sources, facts, clock)]


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


def _event_lines(
    events: list[tuple[int, BriefingEvent]],
    sources: FactSources,
    facts: dict[int, BriefFact],
    clock: UserClock,
) -> list[str]:
    return [
        item_line(fact_id, sources.event_items[fact_id], clock, Voiced(facts[fact_id], False))
        for fact_id, _ in events
    ]


def _by_day(
    events: list[tuple[int, BriefingEvent]],
    sources: FactSources,
    facts: dict[int, BriefFact],
    clock: UserClock,
) -> list[str]:
    """List the events under each day's heading and count, naming the busiest days.

    A day is the busiest only beside a lighter day that has events: equal days have none.
    """
    days = {on: list(group) for on, group in groupby(events, key=lambda pair: pair[1].date)}
    counts = [len(group) for group in days.values()]
    busiest = max(counts) if max(counts) > min(counts) else None
    lines: list[str] = []
    for on, group in days.items():
        busy = ", the week's busiest" if len(group) == busiest else ""
        lines += [
            f"{day(date.fromisoformat(on))}, {len(group)} event(s){busy}:",
            *_event_lines(group, sources, facts, clock),
        ]
    return lines


def _calendar_note(
    events: list[tuple[int, BriefingEvent]],
    sources: FactSources,
    facts: dict[int, BriefFact],
    clock: UserClock,
) -> str:
    gap = sources.calendar.gap
    if gap is not None:
        return CALENDAR_UNAVAILABLE if gap is CalendarGap.UNAVAILABLE else NO_CALENDAR_CONNECTED
    if not events:
        return sources.span.empty
    if sources.span.days > 1:
        return "\n".join(
            [
                f"{sources.span.heading}, {len(events)} event(s):",
                *_by_day(events, sources, facts, clock),
            ]
        )
    return f"{sources.span.heading}:\n" + "\n".join(_event_lines(events, sources, facts, clock))


def _signals_block(
    signals: list[tuple[int, BriefCandidate]],
    facts: dict[int, BriefFact],
    addresses: dict[int, str],
    clock: UserClock,
) -> str:
    """Group the placed app signals per app, important ones first; empty when there are none."""
    if not signals:
        return ""
    ordered = sorted(
        signals, key=lambda pair: (pair[1].app, pair[1].importance is not SignalImportance.HIGH)
    )
    apps = {c.source for _, c in signals}
    lines = [
        f"{SIGNALS_HEADER} {len(signals)} item(s) shown from {len(apps)} app(s). {SHOWN_NOT_TOTAL}"
    ]
    for app, items in groupby(ordered, key=lambda pair: pair[1].app):
        group = list(items)
        lines.append(f"[{app}] {len(group)} item(s) shown")
        lines += [item_line(i, c, clock, Voiced(facts[i], i in addresses)) for i, c in group]
    return "\n".join(lines)


def _recap_lines(recap: WeekRecap) -> list[str]:
    """Say the week's totals as one grouped recap, and what moved and what stuck on each goal."""
    lines: list[str] = []
    if recap.series:
        lines.append(WEEK_IN_NUMBERS_HEADER)
        lines += [
            f"- {s.label}: {SeriesSlot(s.id, SeriesField.TOTAL)} ({series_figures(s)[SeriesField.TOTAL]}"
            f"{f' {s.unit}' if s.unit else ''})"
            for s in recap.series
        ]
    if recap.goals:
        lines.append(GOALS_THIS_WEEK_HEADER)
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
    if not open_count:
        return ONLY_TRACKED_TODOS if tracked_open else OWN_TODOS_EMPTY
    overdue_note = OWN_TODOS_OVERDUE if overdue else ""
    return OWN_TODOS_COUNTED + overdue_note + (TRACKED_BESIDE_OWN if tracked_open else "")
