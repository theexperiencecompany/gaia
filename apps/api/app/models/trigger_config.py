"""Trigger configuration models (Pydantic)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.general import MAX_PAGE_NUMBER


class TriggerFieldConfig(BaseModel):
    """Configuration for a specific trigger field."""

    name: str
    type: Literal["string", "integer", "boolean", "number"]
    description: str
    required: bool = True
    # Matches `type` above: the four JSON-schema scalars a trigger field can be.
    # `bool` leads the union so Pydantic's smart mode never resolves False to 0.
    default: bool | int | float | str | None = None


class TriggerConfigFieldSchema(BaseModel):
    """Schema for a single trigger configuration field."""

    type: Literal["string", "integer", "boolean", "number"]
    default: bool | int | float | str
    min: int | None = None
    max: int | None = None
    options_endpoint: str | None = None
    description: str | None = None


class IndexedTriggerValue(BaseModel):
    """The trigger fields the triggers store persists per entry; its other keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    slug: str
    name: str
    description: str | None
    integration_id: str
    integration_name: str


class TriggerSearchConfigField(BaseModel):
    """One config field of a searched trigger, as the agent reads it."""

    type: Literal["string", "integer", "boolean", "number"]
    description: str | None
    default: bool | int | float | str
    required: bool


class TriggerSearchResult(BaseModel):
    """A trigger matched by semantic search, with the user's connection status and its config fields."""

    trigger_slug: str
    trigger_name: str
    description: str | None
    integration_id: str
    integration_name: str
    is_connected: bool
    config_fields: dict[str, TriggerSearchConfigField]


class WorkflowTriggerSchema(BaseModel):
    """Schema for workflow trigger definitions."""

    slug: str
    composio_slug: str
    name: str
    description: str
    config_schema: dict[str, TriggerConfigFieldSchema] = {}


class WorkflowTriggerResponse(WorkflowTriggerSchema):
    """A ``WorkflowTriggerSchema`` plus the identifiers of the integration that owns it.

    The `/triggers/schema` wire contract consumed by web and mobile.
    """

    provider: str
    integration_id: str


class TriggerOption(BaseModel):
    """A single selectable value for a trigger config field."""

    value: str
    label: str


class TriggerOptionGroup(BaseModel):
    """Options grouped under a parent (cascading dropdowns, e.g. sheets per spreadsheet)."""

    group: str
    options: list[TriggerOption]


class TriggerOptionsParams(BaseModel):
    """The query string of ``GET /triggers/options``."""

    model_config = ConfigDict(frozen=True)

    integration_id: str = Field(description="The integration ID (e.g., 'slack', 'trello')")
    trigger_slug: str = Field(description="The trigger slug (e.g., 'slack_new_message')")
    field_name: str = Field(default="", description="The config field name (e.g., 'channel_id')")
    parent_values: str = Field(
        default="",
        description="Comma-separated parent IDs for cascading options (e.g., 'ws1,ws2')",
    )
    page: int = Field(
        default=1,
        ge=1,
        le=MAX_PAGE_NUMBER,
        description="Page number (starting from 1), for paged handlers",
    )
    search: str = Field(default="", description="Filter options by label substring")

    @property
    def parent_ids(self) -> list[str] | None:
        ids = [value.strip() for value in self.parent_values.split(",") if value.strip()]
        return ids or None


class TriggerOptionsQuery(BaseModel):
    """One request for a trigger config field's dynamic options."""

    model_config = ConfigDict(frozen=True)

    trigger_name: str
    field_name: str
    user_id: str
    integration_id: str
    parent_ids: list[str] | None = None
    page: int = 1
    search: str = ""


class TriggerOptionsResponse(BaseModel):
    """The `/triggers/options` wire contract."""

    options: list[TriggerOption | TriggerOptionGroup]


class TriggerConfig(BaseModel):
    """Configuration for a specific trigger."""

    slug: str
    name: str
    description: str
    # Handed straight to `composio.triggers.create(trigger_config=...)`; the key
    # set is each Composio trigger's own, so it stays an unmodelled payload.
    config: dict[str, Any] | None = None
    config_fields: list[TriggerFieldConfig] | None = None
    auto_activate: bool = True
    workflow_trigger_schema: WorkflowTriggerSchema | None = None
