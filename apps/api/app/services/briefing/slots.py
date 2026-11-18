"""The brief's slots: every count, time and link its prose voices is filled in by code.

The model writes a slot where a figure or a link goes (the grammar is brief_slot_models) and
code parses it into a typed slot and renders it from the facts. Outside its slots the prose
holds no web address, no time, and no figure that is not as it stands in a fact's title, its
own words (a detail, a quote) or a count a slot renders, so it cannot invent a count, a time
or a link; a typed time is sent back naming its slot.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
import re

from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_item_models import ItemState
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.models.brief_slot_models import (
    SLOT_FORMS,
    CountName,
    CountSlot,
    FactField,
    FactSlot,
    SeriesField,
    SeriesSlot,
    SlotKind,
    ValueSlot,
    value_slot_text,
)
from app.services.briefing.clock import UserClock, due_on
from app.services.briefing.formats import weekday


@dataclass(frozen=True)
class BriefFact:
    """What one fact's slots render; time is None when it has none.

    kind is the item's state and words its line's own words beyond the title, which hold
    what prose may claim of it; None for a fact that is no item (an event).
    """

    title: str
    time: str | None = None
    count: int = 1
    kind: ItemState | None = None
    words: str | None = None


def candidate_fact(
    candidate: BriefCandidate,
    clock: UserClock,
    *,
    title: str | None = None,
    kind: ItemState | None = None,
    words: str | None = None,
) -> BriefFact:
    """Return what a pool item's slots render: its title or the brief's words for it, its time or due day, its count."""
    due = due_on(candidate.due_at, clock) if candidate.due_at is not None else None
    return BriefFact(
        title=candidate.title if title is None else title,
        time=candidate.time or due,
        count=candidate.count,
        kind=kind,
        words=words,
    )


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
        SeriesField.PEAK_AT: weekday(date.fromisoformat(peak.x)) if timed else peak.x,
        SeriesField.LOW: figure(min(ys)),
    }
    if timed:
        figures[SeriesField.LATEST] = figure(ys[-1])
    return figures


@dataclass(frozen=True)
class SlotValues:
    """Everything a slot can render: the facts by id, the counts (zeros left out) and series figures."""

    facts: Mapping[int, BriefFact]
    counts: Mapping[CountName, int]
    series: Mapping[str, Mapping[SeriesField, str]] = field(default_factory=dict)
    #: Figures the facts' own words carry ("1x" in a quoted ask), which prose may quote as they stand.
    quoted: frozenset[str] = frozenset()


class SlotError(ValueError):
    """A slot names no count or fact the brief offered."""


_KINDS = "|".join(re.escape(kind.value) for kind in SlotKind)
_FACT = re.escape(SlotKind.FACT.value)
_VALUE_SLOT_RE = re.compile(rf"\[\[({_KINDS}):(\w+)(?:\.(\w+))?\]\]")
LINK_SLOT_RE = re.compile(rf"\[([^\[\]\n]+)\]\({_FACT}:(\d+)\)")
# What is left of a slot the model mangled once every well-formed one is taken out.
_KIND_PREFIXES = "|".join(rf"\b{re.escape(kind.value)}:" for kind in SlotKind)
_SLOT_RESIDUE_RE = re.compile(
    rf"\[[^\[\]\n]*\]\([^)\n]*\)|\S*(?:[\[\]]|\({_FACT}:|{_KIND_PREFIXES})\S*"
)
_WEB_ADDRESS_RE = re.compile(r"\S*(?:://|www\.)\S*")
_TITLE_SLOT_RE = re.compile(rf"\[\[{_FACT}:(\d+)\]\]")
_ANY_SLOT_RE = re.compile(rf"\[\[(?:{_KINDS}):\w+(?:\.\w+)?\]\]")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|\n+")
# A meridiem the prose writes itself, as "[[fact:N.time]] PM" does after a time that holds one.
_MERIDIEM_RE = re.compile(r"\s*([AaPp](?:\.[Mm]\.|[Mm]\b))")
# What a sentence wraps around a word it quotes from a title ("the Q3 interviews,").
_WORD_EDGES = "()\"'.,;:!?"
#: The forms a fact slot takes: its title, and each field.
_FACT_FORMS = SLOT_FORMS[1 : 2 + len(FactField)]


def _either(forms: Iterable[str]) -> str:
    listed = list(forms)
    return f"{', '.join(listed[:-1])} or {listed[-1]}"


def _fact(key: str, values: SlotValues) -> BriefFact:
    fact = values.facts.get(int(key)) if key.isdigit() else None
    if fact is None:
        raise SlotError(f"{SlotKind.FACT.value}:{key} is no fact shown today")
    return fact


def _count_slot(written: str, key: str, field_name: str | None, values: SlotValues) -> CountSlot:
    if field_name is not None:
        raise SlotError(f"{written}: a count slot has no field")
    offered = {slot.value: slot for slot, n in values.counts.items() if n}
    if key not in offered:
        listed = ", ".join(offered) or "none today"
        raise SlotError(
            f"{value_slot_text(SlotKind.COUNT, key)} is not a count the facts list (offered: {listed})"
        )
    return CountSlot(offered[key])


def _series_slot(written: str, key: str, field_name: str | None, values: SlotValues) -> SeriesSlot:
    figures = values.series.get(key)
    if figures is None:
        raise SlotError(f"{written}: {key} is no series shown today")
    offered = {f.value: f for f in figures}
    if field_name not in offered:
        raise SlotError(
            f"{written}: series {key} offers {', '.join(offered)}, as "
            f"{value_slot_text(SlotKind.SERIES, key, 'field')}"
        )
    return SeriesSlot(key, offered[field_name])


def _fact_slot(written: str, key: str, field_name: str | None, values: SlotValues) -> FactSlot:
    fact = _fact(key, values)
    if field_name is None:
        return FactSlot(int(key))
    if field_name == FactField.TIME and fact.time is not None:
        return FactSlot(int(key), FactField.TIME)
    if field_name == FactField.COUNT and fact.count > 1:
        return FactSlot(int(key), FactField.COUNT)
    if field_name in {f.value for f in FactField}:
        raise SlotError(f"{written}: fact {key} has no {field_name}")
    raise SlotError(f"{written}: a fact slot is {_either(_FACT_FORMS)}")


_PARSERS: Mapping[SlotKind, Callable[[str, str, str | None, SlotValues], ValueSlot]] = {
    SlotKind.COUNT: _count_slot,
    SlotKind.FACT: _fact_slot,
    SlotKind.SERIES: _series_slot,
}


def _parsed(match: re.Match[str], values: SlotValues) -> ValueSlot:
    """Parse a written value slot into the slot it names; raises SlotError when the facts hold none."""
    kind, key, field_name = match.groups()
    return _PARSERS[SlotKind(kind)](match.group(0), key, field_name, values)


def _rendered(slot: ValueSlot, values: SlotValues) -> str:
    """Return what a parsed slot renders."""
    if isinstance(slot, CountSlot):
        return str(values.counts[slot.name])
    if isinstance(slot, SeriesSlot):
        return values.series[slot.series_id][slot.field]
    fact = values.facts[slot.fact_id]
    if slot.field is FactField.TIME and fact.time is not None:
        return fact.time
    return str(fact.count) if slot.field is FactField.COUNT else fact.title


def _value(match: re.Match[str], values: SlotValues) -> str:
    return _rendered(_parsed(match, values), values)


def figures_in(texts: Iterable[str]) -> frozenset[str]:
    """Return every word with a digit the texts hold, as prose would quote it."""
    return frozenset(
        word.strip(_WORD_EDGES)
        for text in texts
        for word in text.split()
        if any(ch.isdigit() for ch in word)
    )


def _rendered_by_slot(values: SlotValues) -> list[tuple[str, str]]:
    """Return every slot a typed figure can come from, beside the value it renders.

    A count slot is left out: its figure is in _counted, so prose that types it is never flagged.
    """
    slots = [
        (str(FactSlot(fact_id, FactField.TIME)), fact.time)
        for fact_id, fact in values.facts.items()
        if fact.time is not None
    ]
    slots += [
        (str(SeriesSlot(series_id, figure_field)), text)
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
    words = [word.strip(_WORD_EDGES) for word in text.split()]
    return [word for word in words if any(ch.isdigit() for ch in word) and not _held(word, held)]


def _held(word: str, held: set[str]) -> bool:
    """Say whether a typed word is held figures: as it stands, plural ("1:1s"), or hyphened ("300-user")."""
    if word in held or word.removesuffix("s") in held:
        return True
    parts = word.split("-")
    figures = [part for part in parts if any(ch.isdigit() for ch in part)]
    return len(parts) > 1 and all(_held(part, held) for part in figures)


def _typed_figure_problem(field_name: str, word: str, values: SlotValues) -> str:
    """Name the slot that renders a typed figure, so the retry writes it; else ask for words."""
    # Any word of what a slot renders: the "13" of "Fri Nov 13", the "11" of "11:00 AM".
    slots = [
        slot
        for slot, value in _rendered_by_slot(values)
        if word == value or any(word in (part, part.split(":")[0]) for part in value.split())
    ]
    if slots:
        return f"the {field_name} types {word!r} itself; write {' or '.join(slots)} where it says {word}"
    return (
        f"the {field_name} types {word!r}, a figure no fact carries; say it in words, from the "
        "facts, or leave it out"
    )


def _echo(text: str, match: re.Match[str], value: str) -> re.Match[str] | None:
    """Return what the prose wrote right after a slot that the slot already renders, if anything."""
    echoed = re.compile(rf"\s*(\(?{re.escape(value)}\)?)(?![\w:])").match(text, match.end())
    if echoed is not None:
        return echoed
    meridiem = _MERIDIEM_RE.match(text, match.end())
    return meridiem if meridiem is not None and _MERIDIEM_RE.search(value) else None


def _echo_problems(field_name: str, text: str, values: SlotValues) -> tuple[list[str], str]:
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
                f"the {field_name} writes {echoed.group(1)!r} after {match.group(0)}, which already "
                f"renders {value!r}; drop it"
            )
            spans.append(echoed.span(1))
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return problems, text


def sentences(text: str) -> list[str]:
    """Split prose into its sentences and lines."""
    return [s for s in _SENTENCE_END_RE.split(text) if s.strip()]


def unslotted(text: str) -> str:
    """Return the text as the model typed it outside its slots: each link's phrase, no value slot."""
    return LINK_SLOT_RE.sub(r"\1", _VALUE_SLOT_RE.sub("", text))


def _names_in_words(title: str, sentence: str) -> bool:
    """Whether the sentence says the title in its own words, outside every slot."""
    return any(title.casefold() in words.casefold() for words in _ANY_SLOT_RE.split(sentence))


def _title_echo_problems(field_name: str, text: str, values: SlotValues) -> list[str]:
    """Name each title slot whose sentence already names its fact in words.

    A title several facts share (two 1:1s) is said once per fact, so it is never an echo.
    """
    shared = Counter(fact.title.casefold() for fact in values.facts.values())
    problems: list[str] = []
    for sentence in _SENTENCE_END_RE.split(text):
        for match in _TITLE_SLOT_RE.finditer(sentence):
            fact = values.facts.get(int(match.group(1)))
            if fact is None or shared[fact.title.casefold()] > 1:
                continue
            if _names_in_words(fact.title, sentence):
                problems.append(
                    f"the {field_name} names {fact.title!r} in words and again with "
                    f"{match.group(0)}; keep one"
                )
    return list(dict.fromkeys(problems))


def slot_problems(
    field_name: str, text: str, values: SlotValues, *, may_quote_figures: bool = False
) -> list[str]:
    """Name every slot in one prose field that is malformed or unknown, and every figure it typed.

    may_quote_figures lets the field type figures: an item's wording quotes its own line's.
    """
    problems: list[str] = []
    for match in [*_VALUE_SLOT_RE.finditer(text), *LINK_SLOT_RE.finditer(text)]:
        try:
            if match.re is LINK_SLOT_RE:
                _fact(match.group(2), values)
            else:
                _parsed(match, values)
        except SlotError as exc:
            problems.append(f"the {field_name}: {exc}")
    problems += _title_echo_problems(field_name, text, values)
    echoes, text = _echo_problems(field_name, text, values)
    problems += echoes
    bare = unslotted(text)
    problems += [
        f"the {field_name} has a malformed slot {match.group(0)!r}; write {_either(SLOT_FORMS)} "
        "exactly"
        for match in _SLOT_RESIDUE_RE.finditer(bare)
    ]
    bare = _SLOT_RESIDUE_RE.sub(" ", bare)  # pragma: no mutate — digit-free either way
    typed = [] if may_quote_figures else _typed_figures(bare, values)
    problems += [_typed_figure_problem(field_name, word, values) for word in dict.fromkeys(typed)]
    problems += [
        f"the {field_name} writes the address {match.group(0)!r}; link a phrase with "
        f"({SlotKind.FACT.value}:N)"
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
        if SlotKind(m.group(1)) is SlotKind.FACT and m.group(2).isdigit()
    }
    return named | {int(m.group(2)) for m in LINK_SLOT_RE.finditer(text)}
