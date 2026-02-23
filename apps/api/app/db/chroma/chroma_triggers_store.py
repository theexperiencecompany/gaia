"""ChromaDB-backed store for workflow triggers.

This module provides persistent, hash-based trigger indexing similar to
chroma_tools_store.py. Triggers are indexed with embeddings for semantic search
and only updated when their configuration changes.
"""

import hashlib
from typing import Any

from app.config.loggers import chroma_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.chroma.chromadb import ChromaClient
from langgraph.store.base import PutOp

from .chroma_store import ChromaStore

# Namespace for workflow triggers in the store
TRIGGERS_NAMESPACE = "workflow_triggers"


def _compute_trigger_hash(integration_id: str, trigger: Any) -> str:
    """Compute hash for a trigger based on its configuration.

    Args:
        integration_id: ID of the parent integration
        trigger: Trigger object with slug, name, description

    Returns:
        SHA256 hash string
    """
    # Include all relevant trigger fields in the hash
    content_parts = [
        trigger.slug,
        trigger.name,
        trigger.description or "",
        integration_id,
    ]

    # Include schema if available
    if (
        trigger.workflow_trigger_schema
        and trigger.workflow_trigger_schema.config_schema
    ):
        schema_str = str(trigger.workflow_trigger_schema.config_schema)
        content_parts.append(schema_str)

    content = "::".join(content_parts)
    return hashlib.sha256(content.encode()).hexdigest()


def _build_trigger_description(integration: Any, trigger: Any) -> str:
    """Build description for semantic matching using native trigger info.

    Args:
        integration: OAuth integration config
        trigger: Trigger object

    Returns:
        Description string for embedding
    """
    return (
        f"{trigger.name}. "
        f"{trigger.description or ''}. "
        f"Integration: {integration.name}. "
        f"Category: {integration.category or 'general'}."
    )


def _get_current_triggers_with_hashes() -> dict[str, dict]:
    """Get all current triggers with their hashes.

    Returns:
        Dictionary mapping trigger slugs to their hash and metadata
    """
    current_triggers = {}

    for integration in OAUTH_INTEGRATIONS:
        if not integration.associated_triggers:
            continue

        for trigger in integration.associated_triggers:
            trigger_hash = _compute_trigger_hash(integration.id, trigger)
            rich_description = _build_trigger_description(integration, trigger)

            current_triggers[trigger.slug] = {
                "hash": trigger_hash,
                "slug": trigger.slug,
                "name": trigger.name,
                "description": trigger.description,
                "integration_id": integration.id,
                "integration_name": integration.name,
                "category": integration.category,
                "rich_description": rich_description,
            }

    return current_triggers


async def _get_existing_triggers_from_chroma(collection) -> dict[str, dict]:
    """Fetch existing triggers from ChromaDB collection.

    Args:
        collection: ChromaDB collection instance

    Returns:
        Dictionary mapping trigger slugs to their hash and metadata
    """
    existing_triggers = {}

    try:
        existing_data = await collection.get(include=["metadatas"])
        if (
            existing_data
            and existing_data.get("ids")
            and existing_data.get("metadatas")
        ):
            for doc_id, metadata in zip(
                existing_data["ids"], existing_data["metadatas"] or []
            ):
                if metadata and "::" in doc_id:
                    parts = doc_id.split("::")
                    namespace = parts[0] if len(parts) > 1 else "default"
                    trigger_slug = parts[-1]

                    # Only consider triggers from our namespace
                    if namespace != TRIGGERS_NAMESPACE:
                        continue

                    existing_triggers[trigger_slug] = {
                        "hash": metadata.get("trigger_hash", ""),
                        "namespace": namespace,
                    }
    except Exception as e:
        logger.warning(
            f"Error fetching existing triggers: {e}, will register all triggers"
        )

    return existing_triggers


def _compute_trigger_diff(
    current_triggers: dict[str, dict], existing_triggers: dict[str, dict]
) -> tuple[list[tuple[str, dict]], list[str]]:
    """Compute the difference between current and existing triggers.

    Args:
        current_triggers: Dictionary of current triggers with hashes
        existing_triggers: Dictionary of existing trigger hashes

    Returns:
        Tuple of (triggers_to_upsert, triggers_to_delete)
    """
    triggers_to_upsert = []
    triggers_to_delete = []

    # Find new or modified triggers
    for trigger_slug, trigger_data in current_triggers.items():
        existing = existing_triggers.get(trigger_slug)
        existing_hash = existing["hash"] if existing else None
        if existing_hash != trigger_data["hash"]:
            triggers_to_upsert.append((trigger_slug, trigger_data))

    # Find deleted triggers
    for existing_slug in existing_triggers.keys():
        if existing_slug not in current_triggers:
            triggers_to_delete.append(existing_slug)

    return triggers_to_upsert, triggers_to_delete


def _build_put_operations(
    triggers_to_upsert: list[tuple[str, dict]],
    triggers_to_delete: list[str],
) -> list[PutOp]:
    """Build PutOp operations for upserting and deleting triggers.

    Args:
        triggers_to_upsert: List of (trigger_slug, trigger_data) tuples to upsert
        triggers_to_delete: List of trigger slugs to delete

    Returns:
        List of PutOp operations
    """
    put_ops = []

    # Add upsert operations
    for trigger_slug, trigger_data in triggers_to_upsert:
        put_ops.append(
            PutOp(
                namespace=(TRIGGERS_NAMESPACE,),
                key=trigger_slug,
                value={
                    "slug": trigger_data["slug"],
                    "name": trigger_data["name"],
                    "description": trigger_data["description"],
                    "integration_id": trigger_data["integration_id"],
                    "integration_name": trigger_data["integration_name"],
                    "category": trigger_data.get("category", ""),
                    "rich_description": trigger_data["rich_description"],
                    "trigger_hash": trigger_data["hash"],
                },
                index=["rich_description"],
            )
        )

    # Add delete operations
    for trigger_slug in triggers_to_delete:
        put_ops.append(
            PutOp(
                namespace=(TRIGGERS_NAMESPACE,),
                key=trigger_slug,
                value=None,
            )
        )

    return put_ops


async def _execute_batch_operations(
    store: ChromaStore, put_ops: list[PutOp], batch_size: int = 50
) -> None:
    """Execute put operations in batches.

    Args:
        store: ChromaStore instance
        put_ops: List of PutOp operations to execute
        batch_size: Number of operations per batch
    """
    if not put_ops:
        return

    total_ops = len(put_ops)

    for i in range(0, total_ops, batch_size):
        batch = put_ops[i : i + batch_size]
        await store.abatch(batch)
        logger.info(
            f"Processed triggers batch {i // batch_size + 1}/"
            f"{(total_ops + batch_size - 1) // batch_size}"
        )

    logger.info(f"Successfully updated {total_ops} triggers in ChromaDB")


@lazy_provider(
    name="chroma_triggers_store",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=True,
)
async def initialize_chroma_triggers_store() -> ChromaStore:
    """Initialize and return the ChromaDB-backed triggers store with incremental updates.

    This function:
    1. Creates a ChromaStore with embeddings for triggers
    2. Compares current triggers with stored triggers using hashes
    3. Only updates changed/new/deleted triggers

    Returns:
        ChromaStore instance for triggers
    """
    chroma_client = await ChromaClient.get_client()
    embeddings = await providers.aget("google_embeddings")

    if embeddings is None:
        raise RuntimeError("Embeddings not available for triggers store")

    store = ChromaStore(
        client=chroma_client,
        collection_name="langgraph_triggers_store",
        index={
            "embed": embeddings,
            "dims": 768,
            "fields": ["rich_description"],
        },
    )

    collection = await store._get_collection()

    current_triggers = _get_current_triggers_with_hashes()
    logger.info(f"Found {len(current_triggers)} triggers to manage")

    existing_triggers = await _get_existing_triggers_from_chroma(collection)

    triggers_to_upsert, triggers_to_delete = _compute_trigger_diff(
        current_triggers, existing_triggers
    )

    if not triggers_to_upsert and not triggers_to_delete:
        logger.info("ChromaDB triggers store is up-to-date, no changes needed")
        return store

    logger.info(
        f"Updating ChromaDB triggers store: {len(triggers_to_upsert)} to upsert, "
        f"{len(triggers_to_delete)} to delete"
    )

    put_ops = _build_put_operations(triggers_to_upsert, triggers_to_delete)
    await _execute_batch_operations(store, put_ops)

    return store


async def get_triggers_store() -> ChromaStore:
    """Get the triggers store instance.

    Returns:
        ChromaStore instance for triggers
    """
    store = await providers.aget("chroma_triggers_store")
    if store is None:
        raise RuntimeError("Triggers store not initialized")
    return store
