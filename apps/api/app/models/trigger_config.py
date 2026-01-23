"""Trigger configuration models (Pydantic)."""

from collections.abc import Callable
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class TriggerFieldConfig(BaseModel):
    """Configuration for a specific trigger field."""

    name: str
    type: Literal["string", "integer", "boolean", "number"]
    description: str
    required: bool = True
    default: Optional[Any] = None


class TriggerConfigFieldSchema(BaseModel):
    """Schema for a single trigger configuration field."""

    type: Literal["string", "integer", "boolean", "number"]
    default: Any
    min: Optional[int] = None
    max: Optional[int] = None
    options_endpoint: Optional[str] = None
    description: Optional[str] = None


class WorkflowTriggerSchema(BaseModel):
    """Schema for workflow trigger definitions."""

    slug: str
    composio_slug: str
    name: str
    description: str
    config_schema: Dict[str, TriggerConfigFieldSchema] = {}


class TriggerConfig(BaseModel):
    """Configuration for a specific trigger."""

    slug: str
    name: str
    description: str
    config: Optional[dict] = None
    get_config: Optional[Callable] = None
    config_fields: Optional[List[TriggerFieldConfig]] = None
    auto_activate: bool = True
    workflow_trigger_schema: Optional[WorkflowTriggerSchema] = None
