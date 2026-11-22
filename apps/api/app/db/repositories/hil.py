"""Repositories for the HIL tool caches: the destructiveness verdict and the read-only verdict per tool."""

from app.db.repositories.base import MongoRepository
from app.models.hil_models import (
    HILToolRiskRecord,
    HILToolRiskUpdate,
    ToolReadOnlyVerdict,
    ToolReadOnlyVerdictUpdate,
)


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


class ToolReadOnlyVerdictRepository(
    MongoRepository[ToolReadOnlyVerdict, ToolReadOnlyVerdictUpdate]
):
    collection_name = "tool_read_only_verdicts"
    document_model = ToolReadOnlyVerdict
    update_model = ToolReadOnlyVerdictUpdate
    uses_object_id = True
    cache_policy = None

    async def find_verdict(self, tool_hash: str, classifier: str) -> ToolReadOnlyVerdict | None:
        """Return the verdict this classifier gave this exact name, description and schema, or None."""
        return await self._find_one({"tool_hash": tool_hash, "classifier": classifier})

    async def upsert_verdict(self, verdict: ToolReadOnlyVerdict) -> None:
        """Store the verdict on its tool and classifier; concurrent classifications converge."""
        await self._raw_collection().update_one(
            {"tool_hash": verdict.tool_hash, "classifier": verdict.classifier},
            {"$set": verdict.model_dump(exclude={"id"})},
            upsert=True,
        )


hil_tool_risk_repository = HilToolRiskRepository()
tool_read_only_verdict_repository = ToolReadOnlyVerdictRepository()
