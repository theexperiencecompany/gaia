"""A brief as GAIA composes it: an ordered list of typed blocks over the fact pool, by id only.

BriefComposition is what the composition call answers, one strict schema per kind of block;
code checks it and resolves every id into the stored BriefBlock, which carries the very
points, words and counts the pool held.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import (
    MAX_BRIEF_BLOCKS,
    MAX_ITEMS_PER_BLOCK,
    BriefAction,
    BriefOutcome,
)
from app.models.brief_pool_models import DataSeries, GoalState, QuoteSpan

BriefBlockKind = Literal["lead", "items", "chart", "quote", "progress", "note"]


class ChartKind(StrEnum):
    """How a chart draws its series."""

    BAR = "bar"
    LINE = "line"
    SPARK = "spark"
    STACKED_BAR = "stacked_bar"


class ComposedItem(BaseModel):
    """One pool item placed in a lead or items block, worded for the brief from its own facts."""

    id: int = Field(description="The item's id in the pool")
    action: BriefAction | None = Field(
        description="What the user does about it, when it needs them; else null"
    )
    outcome: BriefOutcome | None = Field(
        description="Where it got to, when it needs nothing from them; else null"
    )
    title: str = Field(description="A noun phrase naming the thing, never a sentence")
    detail: str | None = Field(description="The one fact that matters, or null")


class ComposedLead(BaseModel):
    """The one thing to start on, and what GAIA will do about it."""

    kind: Literal["lead"]
    item: ComposedItem
    offer: str = Field(description="What GAIA does when the user says yes, one short sentence")


class GroupState(StrEnum):
    """What every item of a group is: waiting on the user, done, or still running."""

    NEEDS_YOU = "needs_you"
    DONE = "done"
    IN_PROGRESS = "in_progress"


class ComposedItems(BaseModel):
    """A group of items, all in one state, under a heading GAIA writes."""

    kind: Literal["items"]
    state: GroupState = Field(
        description="needs_you: every item has an action; done: every item finished; "
        "in_progress: every item started and still running"
    )
    heading: str
    items: list[ComposedItem] = Field(min_length=1, max_length=MAX_ITEMS_PER_BLOCK)


class ComposedChart(BaseModel):
    """A chart over pool series, with the one thing to see in it."""

    kind: Literal["chart"]
    chart: ChartKind
    series_ids: list[str]
    title: str
    takeaway: str


class ComposedQuote(BaseModel):
    """Someone's own words from the pool."""

    kind: Literal["quote"]
    quote_id: str


class ComposedProgress(BaseModel):
    """Where one of the pool's goals stands."""

    kind: Literal["progress"]
    goal_id: str


class ComposedNote(BaseModel):
    """A pattern, a heads-up or a suggestion in GAIA's words."""

    kind: Literal["note"]
    text: str


#: One block as the composition writes it. Every field is required and every kind an enum, so a
#: provider that holds replies to their schema can only send a whole block.
ComposedBlock = (
    ComposedLead | ComposedItems | ComposedChart | ComposedQuote | ComposedProgress | ComposedNote
)


class BriefComposition(BaseModel):
    """The composition's answer: the brief's blocks in reading order."""

    blocks: list[ComposedBlock] = Field(max_length=MAX_BRIEF_BLOCKS)


def placed_items(block: ComposedBlock) -> list[ComposedItem]:
    """Return the pool items a block places: the lead's one, a group's, none for the rest."""
    if isinstance(block, ComposedLead):
        return [block.item]
    return block.items if isinstance(block, ComposedItems) else []


class SectionBlock(BaseModel):
    """A lead or items block, stored as the payload section it became (sections[section])."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: Literal["lead", "items"]
    section: int = Field(ge=0)


class ChartBlock(BaseModel):
    """A chart over real series, with the title and takeaway GAIA wrote for it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: Literal["chart"] = "chart"
    chart: ChartKind
    title: str
    takeaway: str
    series: list[DataSeries] = Field(min_length=1)


class QuoteBlock(BaseModel):
    """Someone's own words, set apart."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: Literal["quote"] = "quote"
    quote: QuoteSpan


class ProgressBlock(BaseModel):
    """Where one of the user's goals stands."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: Literal["progress"] = "progress"
    goal: GoalState


class NoteBlock(BaseModel):
    """A pattern GAIA noticed, a heads-up or a suggestion, rendered from its slots."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: Literal["note"] = "note"
    text: str


BriefBlock = Annotated[
    SectionBlock | ChartBlock | QuoteBlock | ProgressBlock | NoteBlock,
    Field(discriminator="kind"),
]
