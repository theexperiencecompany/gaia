"""A brief as GAIA composes it: an ordered list of typed blocks over the fact pool, by id only.

BriefComposition is what the composition call answers, flat so every model can fill it;
code checks it and resolves every id into the stored BriefBlock, which carries the very
points, words and counts the pool held.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefAction, BriefOutcome
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
        default=None, description="What the user does about it, when it needs them; else null"
    )
    outcome: BriefOutcome | None = Field(
        default=None, description="Where it got to, when it needs nothing from them; else null"
    )
    title: str | None = Field(
        default=None, description="A noun phrase naming the thing, never a sentence"
    )
    detail: str | None = Field(default=None, description="The one fact that matters, or null")


class ComposedBlock(BaseModel):
    """One block as the composition writes it; which fields a kind needs is checked in code."""

    kind: BriefBlockKind
    heading: str | None = Field(default=None, description="items: the group's heading")
    items: list[ComposedItem] = Field(
        default_factory=list, description="lead: exactly one item; items: the group's items"
    )
    offer: str | None = Field(default=None, description="lead: what GAIA will do about it")
    series_ids: list[str] = Field(default_factory=list, description="chart: the series it draws")
    chart: ChartKind | None = Field(default=None, description="chart: how it draws them")
    title: str | None = Field(default=None, description="chart: what it shows")
    takeaway: str | None = Field(default=None, description="chart: the one thing to see in it")
    quote_id: str | None = Field(default=None, description="quote: the quote's id")
    goal_id: str | None = Field(default=None, description="progress: the goal's id")
    text: str | None = Field(default=None, description="note: the note itself")


class BriefComposition(BaseModel):
    """The composition's answer: the brief's blocks in reading order."""

    blocks: list[ComposedBlock] = Field(default_factory=list)


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
