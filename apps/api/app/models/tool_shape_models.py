"""Observed tool output shapes — structure learned from real dispatches.

Scoped per ``ResolvedTool.shape_scope``; one document per (scope, tool_name).
``output_schema`` is a genson-inferred JSON schema of keys and types only — no
value is ever stored. Keys are filtered to identifier-shaped names so a dict
keyed by data contributes no property names (``tool_shape_service._sample``),
but that filter is a heuristic: a global-scope record is not a privacy boundary.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import MongoDocument


class ToolOutputShapeDocument(MongoDocument):
    tool_name: str
    # "global" for catalog tools; "mcp:<integration_id>" for MCP tools (see
    # ResolvedTool.shape_scope). One record per (scope, tool_name).
    scope: str = "global"
    output_schema: dict[str, Any]
    call_count: int = 0
    last_seen: datetime


class ToolOutputShapeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_schema: dict[str, Any] | None = None
    call_count: int | None = None
    last_seen: datetime | None = None
