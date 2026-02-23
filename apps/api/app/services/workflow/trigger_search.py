"""
Trigger search service - semantic search over workflow triggers.

This module provides functionality to:
1. Search for triggers matching natural language queries using ChromaDB vector search
2. Get configuration schemas for specific triggers
3. Check user connection status for integrations

Triggers are indexed in ChromaDB by chroma_triggers_store.py at startup.
"""

from typing import Any

from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.chroma.chroma_triggers_store import (
    TRIGGERS_NAMESPACE,
    get_triggers_store,
)


class TriggerSearchService:
    """Service for searching and retrieving trigger information."""

    @classmethod
    async def search(
        cls,
        query: str,
        user_id: str,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        """
        Search for triggers matching the query.

        Uses semantic search via ChromaDB embeddings.
        Returns triggers with connection status and config_fields embedded.

        Args:
            query: Natural language search query
            user_id: User ID for checking connection status
            limit: Maximum number of results (default 15)

        Returns:
            List of trigger dicts with connection status and config_fields
        """
        from app.services.oauth.oauth_service import check_integration_status

        store = await get_triggers_store()

        # Semantic search
        results = await store.asearch(
            (TRIGGERS_NAMESPACE,),
            query=query,
            limit=limit,
        )

        # Enrich with connection status and config_fields
        enriched = []
        checked_integrations: dict[str, bool] = {}

        for item in results:
            value = item.value
            trigger_slug = value.get("slug")
            integration_id = value.get("integration_id", "")

            # Cache connection checks per integration
            if integration_id not in checked_integrations:
                try:
                    is_connected = await check_integration_status(
                        integration_id, user_id
                    )
                    checked_integrations[integration_id] = is_connected
                except Exception as e:
                    logger.warning(
                        f"Failed to check connection for {integration_id}: {e}"
                    )
                    checked_integrations[integration_id] = False

            # Get config schema for this trigger (embedded in results)
            config_fields: dict[str, Any] = {}
            if isinstance(trigger_slug, str):
                schema = await cls.get_schema(trigger_slug)
                if schema:
                    config_fields = schema.get("config_fields", {})

            enriched.append(
                {
                    "trigger_slug": trigger_slug,
                    "trigger_name": value.get("name"),
                    "description": value.get("description"),
                    "integration_id": integration_id,
                    "integration_name": value.get("integration_name"),
                    "is_connected": checked_integrations.get(integration_id, False),
                    "config_fields": config_fields,
                }
            )

        return enriched

    @classmethod
    async def get_schema(cls, trigger_slug: str) -> dict[str, Any] | None:
        """Get configuration schema for a specific trigger.

        Args:
            trigger_slug: The trigger slug to look up

        Returns:
            Schema dict with trigger info and config fields, or None if not found
        """
        for integration in OAUTH_INTEGRATIONS:
            if not integration.associated_triggers:
                continue

            for trigger in integration.associated_triggers:
                if trigger.slug == trigger_slug:
                    schema: dict[str, Any] = {
                        "trigger_slug": trigger.slug,
                        "trigger_name": trigger.name,
                        "description": trigger.description,
                        "integration_id": integration.id,
                        "integration_name": integration.name,
                        "config_fields": {},
                    }

                    # Extract config schema if available
                    if (
                        trigger.workflow_trigger_schema
                        and trigger.workflow_trigger_schema.config_schema
                    ):
                        # Use sentinel to distinguish missing default from explicit None
                        _sentinel = object()
                        for (
                            field_name,
                            field_config,
                        ) in trigger.workflow_trigger_schema.config_schema.items():
                            default_val = getattr(field_config, "default", _sentinel)
                            schema["config_fields"][field_name] = {
                                "type": getattr(field_config, "type", "string"),
                                "description": getattr(field_config, "description", ""),
                                "default": None
                                if default_val is _sentinel
                                else default_val,
                                "required": default_val is _sentinel,
                            }

                    return schema

        return None

    @classmethod
    async def get_all_triggers(cls, user_id: str) -> list[dict[str, Any]]:
        """Get all available triggers with connection status.

        Args:
            user_id: User ID for checking connection status

        Returns:
            List of all triggers with connection status
        """
        from app.services.oauth.oauth_service import check_integration_status

        results = []
        checked_integrations: dict[str, bool] = {}

        for integration in OAUTH_INTEGRATIONS:
            if not integration.associated_triggers:
                continue

            # Check connection once per integration
            if integration.id not in checked_integrations:
                try:
                    is_connected = await check_integration_status(
                        integration.id, user_id
                    )
                    checked_integrations[integration.id] = is_connected
                except Exception:
                    checked_integrations[integration.id] = False

            for trigger in integration.associated_triggers:
                results.append(
                    {
                        "trigger_slug": trigger.slug,
                        "trigger_name": trigger.name,
                        "description": trigger.description,
                        "integration_id": integration.id,
                        "integration_name": integration.name,
                        "is_connected": checked_integrations.get(integration.id, False),
                    }
                )

        return results
