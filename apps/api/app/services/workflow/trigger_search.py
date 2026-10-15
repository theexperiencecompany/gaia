"""
Trigger search service - semantic search over workflow triggers.

This module provides functionality to:
1. Search for triggers matching natural language queries using ChromaDB vector search
2. Get configuration schemas for specific triggers
3. Check user connection status for integrations

Triggers are indexed in ChromaDB by chroma_triggers_store.py at startup.
"""

from app.config.oauth_config import all_integrations
from app.constants.log_tags import LogTag
from app.db.chroma.chroma_triggers_store import (
    TRIGGERS_NAMESPACE,
    get_triggers_store,
)
from app.models.trigger_config import (
    IndexedTriggerValue,
    TriggerSearchConfigField,
    TriggerSearchResult,
)
from shared.py.wide_events import log


class TriggerSearchService:
    """Service for searching and retrieving trigger information."""

    @classmethod
    async def search(
        cls,
        query: str,
        user_id: str,
        limit: int = 15,
    ) -> list[TriggerSearchResult]:
        """Search for triggers matching the query via ChromaDB semantic search, with connection status and config_fields."""
        from app.services.oauth.oauth_service import check_integration_status

        store = await get_triggers_store()

        # Semantic search
        results = await store.asearch(
            (TRIGGERS_NAMESPACE,),
            query=query,
            limit=limit,
        )

        # Enrich with connection status and config_fields
        enriched: list[TriggerSearchResult] = []
        checked_integrations: dict[str, bool] = {}

        for item in results:
            value = IndexedTriggerValue.model_validate(item.value)
            integration_id = value.integration_id

            # Cache connection checks per integration
            if integration_id not in checked_integrations:
                try:
                    is_connected = await check_integration_status(integration_id, user_id)
                    checked_integrations[integration_id] = is_connected
                except Exception as e:
                    log.warning(
                        f"{LogTag.WORKFLOW} Failed to check connection for",
                        integration_id=integration_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        user_id=user_id,
                    )
                    checked_integrations[integration_id] = False

            enriched.append(
                TriggerSearchResult(
                    trigger_slug=value.slug,
                    trigger_name=value.name,
                    description=value.description,
                    integration_id=integration_id,
                    integration_name=value.integration_name,
                    is_connected=checked_integrations[integration_id],
                    config_fields=cls.config_fields(value.slug),
                )
            )

        return enriched

    @staticmethod
    def config_fields(trigger_slug: str) -> dict[str, TriggerSearchConfigField]:
        """Return the trigger's config fields by name; empty when the trigger is unknown or has none."""
        for integration in all_integrations():
            for trigger in integration.associated_triggers or []:
                if trigger.slug != trigger_slug:
                    continue
                schema = trigger.workflow_trigger_schema
                if schema is None:
                    return {}
                # Every config field carries a default, so none is required.
                return {
                    name: TriggerSearchConfigField(
                        type=field.type,
                        description=field.description,
                        default=field.default,
                        required=False,
                    )
                    for name, field in schema.config_schema.items()
                }
        return {}
