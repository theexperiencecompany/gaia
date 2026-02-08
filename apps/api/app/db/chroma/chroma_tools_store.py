"""Modularized helper functions for ChromaStore initialization."""

import hashlib
import inspect
from typing import Any

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import chroma_logger as logger
from app.config.oauth_config import get_subagent_integrations
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.chroma.chromadb import ChromaClient
from app.db.redis import delete_cache, get_cache, set_cache
from langgraph.store.base import PutOp

from .chroma_store import ChromaStore


async def _compute_tool_hash(tool: Any) -> str:
    """Compute hash for a tool based on description and source code."""
    try:
        code_source = inspect.getsource(tool)
        code_source = code_source.strip()
        code_source = "\n".join(line.rstrip() for line in code_source.split("\n"))
        content = f"{tool.description}::{code_source}"
    except (OSError, TypeError, AttributeError):
        logger.debug(
            f"Source unavailable for {getattr(tool, 'name', 'unknown')}, using description hash"
        )
        content = f"{tool.name}::{tool.description}"

    return hashlib.sha256(content.encode()).hexdigest()


async def _get_current_tools_with_hashes(tool_registry) -> dict[str, dict]:
    """Get all current tools with their hashes and namespaces.

    Args:
        tool_registry: Tool registry instance

    Returns:
        Dictionary mapping composite keys (namespace::tool_name) to their hash and namespace info.
        Composite keys prevent collisions when different namespaces have same-named tools.
    """
    current_tools = {}
    tool_dict = tool_registry.get_tool_dict()

    # Add regular tools
    for tool_name, tool in tool_dict.items():
        tool_hash = await _compute_tool_hash(tool)

        tool_category = tool_registry.get_category(
            name=tool_registry.get_category_of_tool(tool.name)
        )
        if tool_category:
            composite_key = f"{tool_category.space}::{tool_name}"
            current_tools[composite_key] = {
                "hash": tool_hash,
                "namespace": tool_category.space,
                "tool": tool,
            }

    # Add subagent tools
    subagent_tools = await _get_subagent_tools()
    current_tools.update(subagent_tools)

    return current_tools


async def _get_subagent_tools() -> dict[str, dict]:
    """Get subagent tools with their hashes.

    Returns:
        Dictionary mapping subagent tool names to their hash and namespace info
    """
    subagent_tools = {}
    subagent_integrations = get_subagent_integrations()

    for integration in subagent_integrations:
        cfg = integration.subagent_config
        if not cfg:
            continue

        provider_name = integration.name
        short_name = integration.short_name or integration.id

        # Create comprehensive description matching handoff_tools pattern
        description = (
            f"{provider_name} ({short_name}). "
            f"{provider_name} specializes in {cfg.domain}. "
            f"Use {provider_name} for: {cfg.use_cases}. "
            f"{provider_name} capabilities: {cfg.capabilities}"
        )

        # Compute hash based on description only
        subagent_hash = hashlib.sha256(description.encode()).hexdigest()

        subagent_tools[f"subagents::subagent:{integration.id}"] = {
            "hash": subagent_hash,
            "namespace": "subagents",
            "description": description,
        }

    return subagent_tools


async def _get_existing_tools_from_chroma(
    collection, namespaces: set[str] | None = None
) -> dict[str, dict]:
    """Fetch existing tools from ChromaDB collection.

    Args:
        collection: ChromaDB collection instance
        namespaces: Optional set of namespaces to filter by. If None, returns all.

    Returns:
        Dictionary mapping composite keys (namespace::tool_name) to their hash
        and namespace info. Composite keys prevent collisions when different
        namespaces have same-named tools.
    """
    existing_tools: dict[str, dict] = {}

    try:
        # Use ChromaDB where filter for efficient namespace filtering
        where_filter: dict[str, Any] | None = None
        if namespaces is not None:
            ns_list = list(namespaces)
            if len(ns_list) == 1:
                where_filter = {"namespace": {"$eq": ns_list[0]}}
            elif len(ns_list) > 1:
                where_filter = {"$or": [{"namespace": {"$eq": ns}} for ns in ns_list]}
            else:
                return existing_tools

        get_kwargs: dict[str, Any] = {"include": ["metadatas"]}
        if where_filter:
            get_kwargs["where"] = where_filter

        existing_data = await collection.get(**get_kwargs)
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

                    # Use full doc_id as composite key to prevent collisions
                    existing_tools[doc_id] = {
                        "hash": metadata.get("tool_hash", ""),
                        "namespace": namespace,
                    }
    except Exception as e:
        logger.warning(f"Error fetching existing tools: {e}, will register all tools")

    return existing_tools


def _compute_tool_diff(
    current_tools: dict[str, dict], existing_tools: dict[str, dict]
) -> tuple[list[tuple[str, dict]], list[tuple[str, str]]]:
    """Compute the difference between current and existing tools.

    Args:
        current_tools: Dictionary of current tools with hashes
        existing_tools: Dictionary of existing tool hashes and namespaces

    Returns:
        Tuple of (tools_to_upsert, tools_to_delete)
    """
    tools_to_upsert = []
    tools_to_delete = []

    # Find new or modified tools
    for tool_name, tool_data in current_tools.items():
        existing = existing_tools.get(tool_name)
        existing_hash = existing["hash"] if existing else None
        if existing_hash != tool_data["hash"]:
            tools_to_upsert.append((tool_name, tool_data))

    # Find deleted tools
    for existing_tool_name, existing_data in existing_tools.items():
        if existing_tool_name not in current_tools:
            tools_to_delete.append((existing_tool_name, existing_data["namespace"]))

    return tools_to_upsert, tools_to_delete


def _build_put_operations(
    tools_to_upsert: list[tuple[str, dict]],
    tools_to_delete: list[tuple[str, str]],
) -> list[PutOp]:
    """Build PutOp operations for upserting and deleting tools.

    Args:
        tools_to_upsert: List of (composite_key, tool_data) tuples to upsert.
            composite_key format: "namespace::tool_name"
        tools_to_delete: List of (composite_key, namespace) tuples to delete.
            composite_key format: "namespace::tool_name"

    Returns:
        List of PutOp operations
    """
    put_ops = []

    # Add upsert operations
    for composite_key, tool_data in tools_to_upsert:
        # Extract actual tool name from composite key (namespace::tool_name)
        tool_name = (
            composite_key.split("::", 1)[-1] if "::" in composite_key else composite_key
        )

        # Handle regular tools vs subagent tools
        if "tool" in tool_data:
            tool = tool_data["tool"]
            description = tool.description
        else:
            # Subagent tool
            description = tool_data["description"]

        put_ops.append(
            PutOp(
                namespace=(tool_data["namespace"],),
                key=tool_name,
                value={
                    "description": description,
                    "tool_hash": tool_data["hash"],
                },
                index=["description"],
            )
        )

    # Add delete operations
    for composite_key, namespace in tools_to_delete:
        tool_name = (
            composite_key.split("::", 1)[-1] if "::" in composite_key else composite_key
        )
        put_ops.append(
            PutOp(
                namespace=(namespace,),
                key=tool_name,
                value=None,
            )
        )

    return put_ops


async def _execute_batch_operations(store, put_ops: list[PutOp], batch_size: int = 50):
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
            f"Processed batch {i // batch_size + 1}/"
            f"{(total_ops + batch_size - 1) // batch_size}"
        )

    logger.info(f"Successfully updated {total_ops} tools in ChromaDB")


async def index_tools_to_store(tools_with_space: list[tuple[Any, str]]):
    """Index tools into ChromaDB store on-demand with full diff logic.

    This function manages tools for a specific namespace:
    1. Checks Redis cache to skip if tools haven't changed
    2. Fetches existing tools from ChromaDB for the namespace
    3. Compares with new tools to determine upsert/delete operations
    4. Removes stale tools, adds/updates new tools

    Args:
        tools_with_space: List of (tool, space_name) tuples to index
    """

    if not tools_with_space:
        return

    namespace = tools_with_space[0][1]

    if not namespace or len(namespace) > 512 or "::" in namespace:
        logger.error(
            f"Invalid namespace: '{namespace}' (empty, too long, or contains ::)"
        )
        return

    # Compute hash of incoming tools for cache check
    tools_signature = "|".join(
        f"{t.name}:{getattr(t, 'description', '')[:200]}" for t, _ in tools_with_space
    )
    tools_hash = hashlib.sha256(tools_signature.encode()).hexdigest()[:16]

    # Check Redis cache BEFORE expensive ChromaDB operations
    # Single source of truth for cache keys: always namespace-based
    cache_key = f"chroma:indexed:{namespace}"
    cached_hash = await get_cache(cache_key)
    if cached_hash == tools_hash:
        logger.debug(f"Namespace '{namespace}' unchanged (Redis cache hit)")
        return

    store = await providers.aget("chroma_tools_store")
    if store is None:
        logger.warning("ChromaDB store not available, skipping tool indexing")
        return

    collection = await store._get_collection()

    current_tools = {}
    for tool, space in tools_with_space:
        tool_hash = await _compute_tool_hash(tool)
        composite_key = f"{space}::{tool.name}"
        current_tools[composite_key] = {
            "hash": tool_hash,
            "namespace": space,
            "tool": tool,
        }

    existing_tools = await _get_existing_tools_from_chroma(collection, {namespace})

    tools_to_upsert, tools_to_delete = _compute_tool_diff(current_tools, existing_tools)

    if not tools_to_upsert and not tools_to_delete:
        logger.info(f"Namespace '{namespace}' is up-to-date, no changes needed")
        # Cache the hash even if no changes (first time seeing this namespace)
        await set_cache(cache_key, tools_hash, ttl=86400)
        return

    logger.info(
        f"Updating namespace '{namespace}': {len(tools_to_upsert)} to upsert, "
        f"{len(tools_to_delete)} to delete"
    )

    put_ops = _build_put_operations(tools_to_upsert, tools_to_delete)
    await _execute_batch_operations(store, put_ops)

    # Cache the hash after successful indexing (24 hour TTL)
    await set_cache(cache_key, tools_hash, ttl=86400)


async def delete_tools_by_namespace(namespace: str) -> int:
    """Delete all tools indexed under a specific namespace.

    Used when a custom integration is deleted to clean up its tools from ChromaDB.

    Args:
        namespace: The namespace to delete tools from (e.g., URL domain)

    Returns:
        Number of tools deleted
    """

    store = await providers.aget("chroma_tools_store")
    if not store:
        logger.warning("ChromaDB store not available for cleanup")
        return 0

    collection = await store._get_collection()

    # Use ChromaDB metadata filter to avoid a full collection scan
    results = await collection.get(
        where={"namespace": {"$eq": namespace}},
        include=[],
    )
    ids_to_delete = results.get("ids", [])

    if ids_to_delete:
        await collection.delete(ids=ids_to_delete)
        logger.info(f"Deleted {len(ids_to_delete)} tools from namespace '{namespace}'")

    # Invalidate Redis cache for this namespace (unified format)
    await delete_cache(f"chroma:indexed:{namespace}")

    return len(ids_to_delete)


@lazy_provider(
    name="chroma_tools_store",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=False,  # Lazy-load only when first accessed (avoids duplicate indexing)
)
async def initialize_chroma_tools_store():
    """Initialize and return the ChromaDB-backed tools store with incremental updates.

    This function:
    1. Creates a ChromaStore with embeddings
    2. Gets namespaces available at init time (general, googlecalendar, subagents)
    3. Only manages tools within those namespaces (doesn't touch provider-specific namespaces)
    4. Updates only changed/new/deleted tools within managed namespaces

    Returns:
        ChromaStore instance
    """
    tool_registry = await get_tool_registry()
    chroma_client = await ChromaClient.get_client()
    embeddings = await providers.aget("google_embeddings")

    if embeddings is None:
        raise RuntimeError("Embeddings not available")

    store = ChromaStore(
        client=chroma_client,
        collection_name="langgraph_tools_store",
        index={
            "embed": embeddings,
            "dims": 768,
            "fields": ["description"],
        },
    )

    collection = await store._get_collection()

    current_tools = await _get_current_tools_with_hashes(tool_registry)

    managed_namespaces = {
        tool_data["namespace"] for tool_data in current_tools.values()
    }
    logger.info(f"Managing namespaces at init: {managed_namespaces}")

    existing_tools = await _get_existing_tools_from_chroma(
        collection, managed_namespaces
    )

    tools_to_upsert, tools_to_delete = _compute_tool_diff(current_tools, existing_tools)

    if not tools_to_upsert and not tools_to_delete:
        logger.info("ChromaDB tools store is up-to-date, no changes needed")
        return store

    logger.info(
        f"Updating ChromaDB tools store: {len(tools_to_upsert)} to upsert, "
        f"{len(tools_to_delete)} to delete"
    )

    put_ops = _build_put_operations(tools_to_upsert, tools_to_delete)
    await _execute_batch_operations(store, put_ops)

    return store
