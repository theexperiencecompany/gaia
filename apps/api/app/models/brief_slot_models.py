"""The brief's slot grammar: every slot a model writes where a count, a time or a link goes, as a typed value.

Each slot prints as the text a model writes, and the forms the prompts and the check's errors
list are printed from the same templates, so the grammar is spelled in one place.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.models.brief_item_models import GroupState


class SlotKind(StrEnum):
    """What a [[kind:key]] value slot renders: a count, a fact or a figure of a series."""

    COUNT = "count"
    FACT = "fact"
    SERIES = "series"


class CountName(StrEnum):
    """The counts a count slot can voice."""

    NEEDS_YOU = GroupState.NEEDS_YOU.value
    DONE = GroupState.DONE.value
    IN_PROGRESS = GroupState.IN_PROGRESS.value
    WHILE_AWAY = "while_away"
    OPEN_TODOS = "open_todos"
    OVERDUE_TODOS = "overdue_todos"
    #: GAIA's open tracked work, each subject once, however much the brief places.
    OPEN_TRACKED = "open_tracked"
    EVENTS = "events"


class FactField(StrEnum):
    """What a fact slot voices besides the fact's title."""

    TIME = "time"
    COUNT = "count"


class SeriesField(StrEnum):
    """What a series slot voices."""

    TOTAL = "total"
    LATEST = "latest"
    PEAK = "peak"
    PEAK_AT = "peak_at"
    LOW = "low"


def value_slot_text(kind: SlotKind, key: str, field: str | None = None) -> str:
    """Spell a value slot: [[kind:key]], or [[kind:key.field]]."""
    return f"[[{kind.value}:{key}{'' if field is None else f'.{field}'}]]"


def link_slot_text(phrase: str, fact_id: str) -> str:
    """Spell a link slot: [phrase](fact:N)."""
    return f"[{phrase}]({SlotKind.FACT.value}:{fact_id})"


@dataclass(frozen=True)
class CountSlot:
    """[[count:name]]: one of the counts the facts list."""

    name: CountName

    def __str__(self) -> str:
        return value_slot_text(SlotKind.COUNT, self.name.value)


@dataclass(frozen=True)
class FactSlot:
    """[[fact:N]] is fact N's title; with a field, its time or how many requests it stands for."""

    fact_id: int
    field: FactField | None = None

    def __str__(self) -> str:
        return value_slot_text(
            SlotKind.FACT, str(self.fact_id), None if self.field is None else self.field.value
        )


@dataclass(frozen=True)
class SeriesSlot:
    """[[series:ID.field]]: one figure of a series."""

    series_id: str
    field: SeriesField

    def __str__(self) -> str:
        return value_slot_text(SlotKind.SERIES, self.series_id, self.field.value)


@dataclass(frozen=True)
class LinkSlot:
    """[the phrase](fact:N): the phrase, linked to what fact N opens when it opens anything."""

    phrase: str
    fact_id: int

    def __str__(self) -> str:
        return link_slot_text(self.phrase, str(self.fact_id))


ValueSlot = CountSlot | FactSlot | SeriesSlot

#: The placeholders the grammar is taught with: a fact's number, a series' id, a field, a phrase.
FACT_PLACEHOLDER = "N"
SERIES_PLACEHOLDER = "ID"
PHRASE_PLACEHOLDER = "the phrase"
#: Every form a slot takes, as the prompts and the check's errors list them.
SLOT_FORMS: tuple[str, ...] = (
    value_slot_text(SlotKind.COUNT, "name"),
    value_slot_text(SlotKind.FACT, FACT_PLACEHOLDER),
    *(value_slot_text(SlotKind.FACT, FACT_PLACEHOLDER, f.value) for f in FactField),
    value_slot_text(SlotKind.SERIES, SERIES_PLACEHOLDER, "field"),
    link_slot_text(PHRASE_PLACEHOLDER, FACT_PLACEHOLDER),
)
