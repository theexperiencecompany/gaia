"""What a brief can show besides its items: numeric series, verbatim quotes and goals, all built by code.

The composition names these by id only; every number, word and date a chart, quote or
progress block shows is the one stored here.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SeriesShape(StrEnum):
    """How a series' points are laid out, which decides the charts that can draw it."""

    #: One point per local day, oldest first; x is the ISO date.
    TIME_SERIES = "time_series"
    #: One point per category; x is the category's name.
    CATEGORICAL = "categorical"


class SeriesPoint(BaseModel):
    """One computed point: a day or a category, and its value."""

    model_config = ConfigDict(frozen=True)

    x: str = Field(min_length=1)
    y: float


class DataSeries(BaseModel):
    """Numeric history from one real source, counted or summed by code."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    label: str = Field(
        min_length=1, description='What is counted: "Emails handled", "Meeting hours"'
    )
    unit: str = Field(min_length=1, description='What one y counts: "emails", "hours", "USD"')
    #: An integration id, or GAIA_SOURCE for GAIA's own work.
    source: str
    app: str = Field(description="The source's display name")
    shape: SeriesShape
    points: list[SeriesPoint] = Field(min_length=1)


class QuoteSpan(BaseModel):
    """Someone's own words, verbatim as their app holds them, with who wrote them and where."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    text: str = Field(min_length=1)
    author: str = Field(min_length=1)
    #: The integration the words were read from.
    source: str
    app: str
    url: str | None = None
    #: The pool item the words belong to.
    item_id: int


class GoalOrigin(StrEnum):
    """Where GAIA learned the goal."""

    ONBOARDING = "onboarding"
    MEMORY = "memory"


class GoalState(BaseModel):
    """A goal the user stated, and the work linked to it, counted from their todos."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    statement: str = Field(min_length=1)
    origin: GoalOrigin
    #: Linked todos completed in the brief's window.
    done: int = Field(ge=0)
    #: Linked todos still open.
    open: int = Field(ge=0)
    #: The linked todos' titles, finished ones first.
    linked: list[str] = Field(default_factory=list)
