"""The brief's slots: every count, time and link its prose voices is filled in by code.

The model writes a slot where a figure or a link goes and code renders it from the facts:
- [[count:needs_you]]: one of the non-zero counts the facts list (CountSlot);
- [[fact:12]]: fact 12's title; [[fact:12.time]]: its time or date; [[fact:12.count]]:
  how many requests it stands for;
- [[series:meeting_hours.peak]]: a figure of a series: its total, latest, peak, low, or
  peak_at (the day or category the peak fell on);
- [the phrase](fact:12): the phrase, linked to what fact 12 opens when it opens anything.
Outside its slots the prose holds no web address, no time, and no figure that is not as it
stands in a fact's title, its own words (a detail, a quote) or a count a slot renders, so it
cannot invent a count, a time or a link; a typed time is sent back naming its slot.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
import re

from app.models.brief_pool_models import DataSeries, SeriesShape


class CountSlot(StrEnum):
    """The counts a [[count:...]] slot can voice."""

    NEEDS_YOU = "needs_you"
    DONE = "done"
    IN_PROGRESS = "in_progress"
    WHILE_AWAY = "while_away"
    OPEN_TODOS = "open_todos"
    EVENTS = "events"


class FactField(StrEnum):
    """What a [[fact:N.field]] slot voices besides the fact's title."""

    TIME = "time"
    COUNT = "count"


@dataclass(frozen=True)
class BriefFact:
    """What one fact's slots render; time is None when it has none."""

    title: str
    time: str | None = None
    count: int = 1


class SeriesField(StrEnum):
    """What a [[series:ID.field]] slot voices."""

    TOTAL = "total"
    LATEST = "latest"
    PEAK = "peak"
    PEAK_AT = "peak_at"
    LOW = "low"


def figure(value: float) -> str:
    """Say a computed value as the brief writes it: 2 for 2.0, 2.5 for 2.5."""
    return f"{value:g}"


def series_figures(series: DataSeries) -> dict[SeriesField, str]:
    """Return what each series slot renders; a categorical series has no latest."""
    ys = [p.y for p in series.points]
    peak = max(series.points, key=lambda p: p.y)
    timed = series.shape is SeriesShape.TIME_SERIES
    figures = {
        SeriesField.TOTAL: figure(sum(ys)),
        SeriesField.PEAK: figure(peak.y),
        SeriesField.PEAK_AT: date.fromisoformat(peak.x).strftime("%A") if timed else peak.x,
        SeriesField.LOW: figure(min(ys)),
    }
    if timed:
        figures[SeriesField.LATEST] = figure(ys[-1])
    return figures


@dataclass(frozen=True)
class SlotValues:
    """Everything a slot can render: the facts by id, the counts (zeros left out) and series figures."""

    facts: Mapping[int, BriefFact]
    counts: Mapping[CountSlot, int]
    series: Mapping[str, Mapping[SeriesField, str]] = field(default_factory=dict)
    #: Figures the facts' own words carry ("1x" in a quoted ask), which prose may quote as they stand.
    quoted: frozenset[str] = frozenset()


class SlotError(ValueError):
    """A slot names no count or fact the brief offered."""


_VALUE_SLOT_RE = re.compile(r"\[\[(count|fact|series):(\w+)(?:\.(\w+))?\]\]")
LINK_SLOT_RE = re.compile(r"\[([^\[\]\n]+)\]\(fact:(\d+)\)")
# What is left of a slot the model mangled once every well-formed one is taken out.
_SLOT_RESIDUE_RE = re.compile(
    r"\[[^\[\]\n]*\]\([^)\n]*\)|\S*(?:[\[\]]|\(fact:|\bfact:|\bcount:|\bseries:)\S*"
)
_WEB_ADDRESS_RE = re.compile(r"\S*(?:://|www\.)\S*")
# A meridiem the prose writes itself, as "[[fact:N.time]] PM" does after a time that holds one.
_MERIDIEM_RE = re.compile(r"\s*([AaPp](?:\.[Mm]\.|[Mm]\b))")
# What a sentence wraps around a word it quotes from a title ("the Q3 interviews,").
_WORD_EDGES = "()\"'.,;:!?"


def _count(key: str, values: SlotValues) -> int:
    offered = {slot.value: n for slot, n in values.counts.items() if n}
    if key not in offered:
        listed = ", ".join(offered) or "none today"
        raise SlotError(f"[[count:{key}]] is not a count the facts list (offered: {listed})")
    return offered[key]


def _fact(key: str, values: SlotValues) -> BriefFact:
    fact = values.facts.get(int(key)) if key.isdigit() else None
    if fact is None:
        raise SlotError(f"fact:{key} is no fact shown today")
    return fact


def _series_value(slot: str, key: str, field_name: str | None, values: SlotValues) -> str:
    figures = values.series.get(key)
    if figures is None:
        raise SlotError(f"{slot}: {key} is no series shown today")
    offered = {f.value: text for f, text in figures.items()}
    if field_name not in offered:
        raise SlotError(
            f"{slot}: series {key} offers {', '.join(offered)}, as [[series:{key}.field]]"
        )
    return offered[field_name]


def _value(match: re.Match[str], values: SlotValues) -> str:
    kind, key, field = match.groups()
    slot = match.group(0)
    if kind == "count":
        if field is not None:
            raise SlotError(f"{slot}: a count slot has no field")
        return str(_count(key, values))
    if kind == "series":
        return _series_value(slot, key, field, values)
    fact = _fact(key, values)
    if field is None:
        return fact.title
    if field == FactField.TIME and fact.time is not None:
        return fact.time
    if field == FactField.COUNT and fact.count > 1:
        return str(fact.count)
    if field in {f.value for f in FactField}:
        raise SlotError(f"{slot}: fact {key} has no {field}")
    raise SlotError(f"{slot}: a fact slot is [[fact:N]], [[fact:N.time]] or [[fact:N.count]]")


def figures_in(texts: Iterable[str]) -> frozenset[str]:
    """Return every word with a digit the texts hold, as prose would quote it."""
    return frozenset(
        word.strip(_WORD_EDGES)
        for text in texts
        for word in text.split()
        if any(ch.isdigit() for ch in word)
    )


def _rendered_by_slot(values: SlotValues) -> list[tuple[str, str]]:
    """Return every slot a figure comes from, beside the value it renders."""
    slots = [(f"[[count:{slot.value}]]", str(n)) for slot, n in values.counts.items() if n]
    for fact_id, fact in values.facts.items():
        if fact.count > 1:
            slots.append((f"[[fact:{fact_id}.count]]", str(fact.count)))
        if fact.time is not None:
            slots.append((f"[[fact:{fact_id}.time]]", fact.time))
    slots += [
        (f"[[series:{series_id}.{figure_field.value}]]", text)
        for series_id, figures in values.series.items()
        for figure_field, text in figures.items()
    ]
    return slots


def _counted(values: SlotValues) -> set[str]:
    """Return every count a slot renders: a [COUNTS] count, a request count, a series figure.

    A count typed as it stands is the same figure its slot renders. Times are never counted
    here: an event is referred to through its time slot.
    """
    counted = {str(n) for n in values.counts.values() if n}
    counted |= {str(fact.count) for fact in values.facts.values() if fact.count > 1}
    counted |= {text for figures in values.series.values() for text in figures.values()}
    return counted


def _typed_figures(text: str, values: SlotValues) -> list[str]:
    """Return each word with a digit no fact carries as it stands: no title, own words or count."""
    held = (
        {word.strip(_WORD_EDGES) for fact in values.facts.values() for word in fact.title.split()}
        | values.quoted
        | _counted(values)
    )
    return [
        word.strip(_WORD_EDGES)
        for word in text.split()
        if any(ch.isdigit() for ch in word) and word.strip(_WORD_EDGES) not in held
    ]


def _typed_figure_problem(field: str, word: str, values: SlotValues) -> str:
    """Name the slot that renders a typed figure, so the retry writes it; else ask for words."""
    slots = [
        slot
        for slot, value in _rendered_by_slot(values)
        if word in (value, value.split()[0], value.split()[0].split(":")[0])
    ]
    if slots:
        return f"the {field} types {word!r} itself; write {' or '.join(slots)} where it says {word}"
    return (
        f"the {field} types {word!r}, a figure no fact carries; say it in words, from the "
        "facts, or leave it out"
    )


def _echo(text: str, match: re.Match[str], value: str) -> re.Match[str] | None:
    """Return what the prose wrote right after a slot that the slot already renders, if anything."""
    echoed = re.compile(rf"\s*(\(?{re.escape(value)}\)?)(?![\w:])").match(text, match.end())
    if echoed is not None:
        return echoed
    meridiem = _MERIDIEM_RE.match(text, match.end())
    return meridiem if meridiem is not None and _MERIDIEM_RE.search(value) else None


def _echo_problems(field: str, text: str, values: SlotValues) -> tuple[list[str], str]:
    """Name each figure written after a slot that renders it; return them and the text without them."""
    problems: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in _VALUE_SLOT_RE.finditer(text):
        try:
            value = _value(match, values)
        except SlotError:
            continue
        echoed = _echo(text, match, value)
        if echoed is not None:
            problems.append(
                f"the {field} writes {echoed.group(1)!r} after {match.group(0)}, which already "
                f"renders {value!r}; drop it"
            )
            spans.append(echoed.span(1))
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return problems, text


def slot_problems(
    field: str, text: str, values: SlotValues, *, figures_are_slots: bool = True
) -> list[str]:
    """Name every slot in one prose field that is malformed or unknown, and every figure it typed.

    figures_are_slots False lets the field type figures: an item's wording quotes its own line's.
    """
    problems: list[str] = []
    for match in [*_VALUE_SLOT_RE.finditer(text), *LINK_SLOT_RE.finditer(text)]:
        try:
            if match.re is LINK_SLOT_RE:
                _fact(match.group(2), values)
            else:
                _value(match, values)
        except SlotError as exc:
            problems.append(f"the {field}: {exc}")
    echoes, text = _echo_problems(field, text, values)
    problems += echoes
    bare = LINK_SLOT_RE.sub(r"\1", _VALUE_SLOT_RE.sub("", text))
    problems += [
        f"the {field} has a malformed slot {match.group(0)!r}; write [[count:name]], "
        "[[fact:N]], [[fact:N.time]], [[fact:N.count]], [[series:ID.field]] or "
        "[the phrase](fact:N) exactly"
        for match in _SLOT_RESIDUE_RE.finditer(bare)
    ]
    bare = _SLOT_RESIDUE_RE.sub(" ", bare)
    typed = _typed_figures(bare, values) if figures_are_slots else []
    problems += [_typed_figure_problem(field, word, values) for word in dict.fromkeys(typed)]
    problems += [
        f"the {field} writes the address {match.group(0)!r}; link a phrase with (fact:N)"
        for match in _WEB_ADDRESS_RE.finditer(bare)
    ]
    return problems


def render_slots(text: str, values: SlotValues, links: Mapping[int, str]) -> str:
    """Fill every slot; a fact's phrase gets the fact's address in links once, else stays text.

    Raises SlotError on a slot slot_problems would have named.
    """
    linked: set[int] = set()

    def link(match: re.Match[str]) -> str:
        phrase, fact_id = match.group(1), int(match.group(2))
        _fact(match.group(2), values)
        url = links.get(fact_id)
        if url is None or fact_id in linked:
            return phrase
        linked.add(fact_id)
        return f"[{phrase}]({url})"

    return _VALUE_SLOT_RE.sub(lambda m: _value(m, values), LINK_SLOT_RE.sub(link, text))


def referenced_facts(text: str) -> set[int]:
    """Return the id of every fact a slot in the text speaks of."""
    named = {
        int(m.group(2))
        for m in _VALUE_SLOT_RE.finditer(text)
        if m.group(1) == "fact" and m.group(2).isdigit()
    }
    return named | {int(m.group(2)) for m in LINK_SLOT_RE.finditer(text)}
