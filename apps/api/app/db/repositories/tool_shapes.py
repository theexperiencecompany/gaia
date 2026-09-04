"""Repository for the ``tool_output_shapes`` collection — observed tool shapes.

Keyed by the business ``(scope, tool_name)`` pair; the incidental Mongo ``_id``
never surfaces above this boundary. ``scope`` is what keeps a private MCP
server's shapes invisible to other users (see ResolvedTool.shape_scope).
"""

from datetime import UTC, datetime
from typing import Any

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.tool_shape_models import ToolOutputShapeDocument, ToolOutputShapeUpdate


class ToolShapesRepository(MongoRepository[ToolOutputShapeDocument, ToolOutputShapeUpdate]):
    collection_name = "tool_output_shapes"
    document_model = ToolOutputShapeDocument
    update_model = ToolOutputShapeUpdate
    uses_object_id = True
    identity_field = "tool_name"
    cache_policy = None

    async def get_shape(self, scope: str, tool_name: str) -> ToolOutputShapeDocument | None:
        return await self._find_one({"scope": scope, "tool_name": tool_name})

    async def record(self, scope: str, tool_name: str, output_schema: dict[str, Any]) -> None:
        """Store the merged schema for one more observation of ``tool_name``."""
        await self._apply_raw_update(
            {"scope": scope, "tool_name": tool_name},
            {
                "$set": {"output_schema": output_schema, "last_seen": datetime.now(UTC)},
                "$inc": {"call_count": 1},
            },
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
            return_document=False,
        )


tool_shapes_repository = ToolShapesRepository()
