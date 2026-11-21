"""task_templates: published and curated tasks anyone can start from.

A template is a copy taken at publish time; the task it came from goes on separately.
Its id is the published workflow's id, so a link by id or by slug still resolves.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.tasks import TemplateOrigin, WhenKind
from app.db.repositories.base import MongoDocument


class TemplateNoWhen(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.NONE] = WhenKind.NONE


class TemplateRepeatWhen(BaseModel):
    """The schedule the card advertises, which using the template reproduces."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.REPEAT] = WhenKind.REPEAT
    rule: str = Field(min_length=1)
    timezone: str | None = None


class TemplateEventWhen(BaseModel):
    """The app event the card advertises, with its registration settings."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[WhenKind.EVENT] = WhenKind.EVENT
    trigger_name: str = Field(min_length=1)
    trigger_data: dict[str, Any] = Field(default_factory=dict)


TemplateWhen = Annotated[
    TemplateNoWhen | TemplateRepeatWhen | TemplateEventWhen, Field(discriminator="kind")
]


class TaskTemplateDocument(MongoDocument):
    """A template as stored; its id is the string _id."""

    title: str = Field(min_length=1)
    body: str
    #: The one-line promise a card shows under the title.
    summary: str = ""
    icon: str | None = None
    icon_color: str | None = None
    when: TemplateWhen = Field(default_factory=TemplateNoWhen)
    integration_ids: list[str] = Field(default_factory=list)
    #: The tool categories its card shows and its related list matches on.
    tool_categories: list[str] = Field(default_factory=list)
    slug: str = Field(min_length=1)
    origin: TemplateOrigin
    #: The publishing user's id; GAIA's own user id on a curated template.
    creator_id: str
    #: The use-case categories a curated template is listed under.
    categories: list[str] = Field(default_factory=list)
    #: How many times the card says it ran: measured on a community template, curated otherwise.
    run_count: int = Field(default=0, ge=0)
    #: The task this template was published from; None on a curated one.
    source_task_id: str | None = None
    #: Set on a curated card for a system task, so using it finds the one already set up.
    system_key: str | None = None
    source_integration: str | None = None
    created_at: datetime
    updated_at: datetime
