"""Modularized helper functions for ChromaStore initialization."""

import hashlib
import inspect
from typing import Any

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import chroma_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.chroma.chromadb import ChromaClient
from langgraph.store.base import PutOp

from .chroma_store import ChromaStore


async def _compute_tool_hash(tool: Any) -> str:
    """Compute hash for a tool based on description and source code.

    Args:
        tool: Tool object with name and description attributes

    Returns:
        SHA256 hash string
    """
    try:
        code_source = inspect.getsource(tool)
        code_source = code_source.strip()
        code_source = "\n".join(line.rstrip() for line in code_source.split("\n"))
        content = f"{tool.description}::{code_source}"
    except (OSError, TypeError, AttributeError):
        # Fallback to description-only hash if source unavailable
        content = f"{tool.name}::{tool.description}"

    return hashlib.sha256(content.encode()).hexdigest()


async def _get_current_tools_with_hashes(tool_registry) -> dict[str, dict]:
    """Get all current tools with their hashes and namespaces.

    Args:
        tool_registry: Tool registry instance

    Returns:
        Dictionary mapping tool names to their hash and namespace info
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
            current_tools[tool_name] = {
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

    subagent_integrations = [
        integration
        for integration in OAUTH_INTEGRATIONS
        if integration.subagent_config and integration.subagent_config.has_subagent
    ]

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

        subagent_tools[f"subagent:{integration.id}"] = {
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
        Dictionary mapping tool names to their hash and namespace info
    """
    existing_tools = {}

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
                    tool_name = parts[-1]

                    if namespaces is not None and namespace not in namespaces:
                        continue

                    existing_tools[tool_name] = {
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
        tools_to_upsert: List of (tool_name, tool_data) tuples to upsert
        tools_to_delete: List of (tool_name, namespace) tuples to delete

    Returns:
        List of PutOp operations
    """
    put_ops = []

    # Add upsert operations
    for tool_name, tool_data in tools_to_upsert:
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
    for tool_name, namespace in tools_to_delete:
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
    1. Fetches existing tools from ChromaDB for the namespace
    2. Compares with new tools to determine upsert/delete operations
    3. Removes stale tools, adds/updates new tools

    Args:
        tools_with_space: List of (tool, space_name) tuples to index
    """
    from app.core.lazy_loader import providers

    if not tools_with_space:
        return

    store = await providers.aget("chroma_tools_store")
    if store is None:
        logger.warning("ChromaDB store not available, skipping tool indexing")
        return

    namespace = tools_with_space[0][1]
    collection = await store._get_collection()

    current_tools = {}
    for tool, space in tools_with_space:
        tool_hash = await _compute_tool_hash(tool)
        current_tools[tool.name] = {
            "hash": tool_hash,
            "namespace": space,
            "tool": tool,
        }

    existing_tools = await _get_existing_tools_from_chroma(collection, {namespace})

    tools_to_upsert, tools_to_delete = _compute_tool_diff(current_tools, existing_tools)

    if not tools_to_upsert and not tools_to_delete:
        logger.info(f"Namespace '{namespace}' is up-to-date, no changes needed")
        return

    logger.info(
        f"Updating namespace '{namespace}': {len(tools_to_upsert)} to upsert, "
        f"{len(tools_to_delete)} to delete"
    )

    put_ops = _build_put_operations(tools_to_upsert, tools_to_delete)
    await _execute_batch_operations(store, put_ops)


@lazy_provider(
    name="chroma_tools_store",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=False,
)
async def initialize_chroma_tools_store():
    """Initialize and return the ChromaDB-backed tools store with incremental updates.

    This function:
    1. Creates a ChromaStore with embeddings
    2. Gets namespaces available at init time (general, google_calendar, subagents)
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
