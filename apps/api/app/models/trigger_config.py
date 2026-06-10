"""Trigger configuration models (Pydantic)."""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel


class TriggerFieldConfig(BaseModel):
    """Configuration for a specific trigger field."""

    name: str
    type: Literal["string", "integer", "boolean", "number"]
    description: str
    required: bool = True
    default: Any | None = None


class TriggerConfigFieldSchema(BaseModel):
    """Schema for a single trigger configuration field."""

    type: Literal["string", "integer", "boolean", "number"]
    default: Any
    min: int | None = None
    max: int | None = None
    options_endpoint: str | None = None
    description: str | None = None


class WorkflowTriggerSchema(BaseModel):
    """Schema for workflow trigger definitions."""

    slug: str
    composio_slug: str
    name: str
    description: str
    config_schema: dict[str, TriggerConfigFieldSchema] = {}


class TriggerConfig(BaseModel):
    """Configuration for a specific trigger."""

    slug: str
    name: str
    description: str
    config: dict | None = None
    get_config: Callable | None = None
    config_fields: list[TriggerFieldConfig] | None = None
    auto_activate: bool = True
    workflow_trigger_schema: WorkflowTriggerSchema | None = None
