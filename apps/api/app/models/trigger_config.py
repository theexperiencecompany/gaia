"""Trigger configuration models (Pydantic)."""

from typing import Literal

from pydantic import BaseModel


class TriggerFieldConfig(BaseModel):  # type: ignore[explicit-any]
    """Configuration for a specific trigger field."""

    name: str
    type: Literal["string", "integer", "boolean", "number"]
    description: str
    required: bool = True
    # Matches `type` above: the four JSON-schema scalars a trigger field can be.
    # `bool` leads the union so Pydantic's smart mode never resolves False to 0.
    default: bool | int | float | str | None = None


class TriggerConfigFieldSchema(BaseModel):  # type: ignore[explicit-any]
    """Schema for a single trigger configuration field."""

    type: Literal["string", "integer", "boolean", "number"]
    default: bool | int | float | str
    min: int | None = None
    max: int | None = None
    options_endpoint: str | None = None
    description: str | None = None


class WorkflowTriggerSchema(BaseModel):  # type: ignore[explicit-any]
    """Schema for workflow trigger definitions."""

    slug: str
    composio_slug: str
    name: str
    description: str
    config_schema: dict[str, TriggerConfigFieldSchema] = {}


class WorkflowTriggerResponse(WorkflowTriggerSchema):  # type: ignore[explicit-any]
    """A ``WorkflowTriggerSchema`` plus the identifiers of the integration that owns it.

    The `/triggers/schema` wire contract consumed by web and mobile.
    """

    provider: str
    integration_id: str


class TriggerOption(BaseModel):  # type: ignore[explicit-any]
    """A single selectable value for a trigger config field."""

    value: str
    label: str


class TriggerOptionGroup(BaseModel):  # type: ignore[explicit-any]
    """Options grouped under a parent (cascading dropdowns, e.g. sheets per spreadsheet)."""

    group: str
    options: list[TriggerOption]


class TriggerOptionsResponse(BaseModel):  # type: ignore[explicit-any]
    """The `/triggers/options` wire contract."""

    options: list[TriggerOption | TriggerOptionGroup]


class TriggerConfig(BaseModel):  # type: ignore[explicit-any]
    """Configuration for a specific trigger."""

    slug: str
    name: str
    description: str
    # Handed straight to `composio.triggers.create(trigger_config=...)`; the key
    # set is each Composio trigger's own, so it stays an unmodelled payload.
    config: dict[str, object] | None = None
    config_fields: list[TriggerFieldConfig] | None = None
    auto_activate: bool = True
    workflow_trigger_schema: WorkflowTriggerSchema | None = None
