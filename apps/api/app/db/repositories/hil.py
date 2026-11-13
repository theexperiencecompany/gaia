"""Repository for the HIL tool-risk cache: one stored destructiveness verdict per custom tool.

Uncached (cache_policy = None): a verdict is read once per classification and
refreshed in place when the tool's description changes.
"""

from app.db.repositories.base import MongoRepository
from app.models.hil_models import HILToolRiskRecord, HILToolRiskUpdate


class HilToolRiskRepository(MongoRepository[HILToolRiskRecord, HILToolRiskUpdate]):
    collection_name = "hil_tool_risk"
    document_model = HILToolRiskRecord
    update_model = HILToolRiskUpdate
    uses_object_id = True
    cache_policy = None

    async def find_classification(
        self, key: str, description_hash: str
    ) -> HILToolRiskRecord | None:
        """Return the stored verdict for this exact tool+description, or None.

        key is hil_tool_key: the bare name, or mcp:<integration_id>:<server_name>.
        """
        return await self._find_one({"tool_name": key, "description_hash": description_hash})

    async def upsert_classification(self, record: HILToolRiskRecord) -> None:
        """Store (or refresh) the verdict, keyed by tool+description.

        An upsert on the business key rather than create: a changed
        description re-classifies and must overwrite the old verdict in place.
        """
        await self._raw_collection().update_one(
            {"tool_name": record.tool_name, "description_hash": record.description_hash},
            {"$set": record.model_dump(exclude={"id"})},
            upsert=True,
        )


hil_tool_risk_repository = HilToolRiskRepository()
