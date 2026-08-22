"""Modularized helper functions for ChromaStore initialization."""

from collections.abc import Callable, Sequence
import hashlib
import inspect
from typing import Any, NotRequired, Protocol, TypedDict, cast

from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.api.types import Where
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import PutOp

from app.agents.core.subagents.registry import all_subagents
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.chroma.chromadb import ChromaClient
from app.db.redis import delete_cache, get_cache, set_cache
from shared.py.wide_events import VectorContext, log

from .chroma_store import ChromaStore


class IndexableTool(Protocol):
    """The only surface indexing reads off a tool: its name and description.

    A ``Protocol`` rather than ``BaseTool`` because the provider-catalog warmup
    deliberately indexes ``_CatalogToolMeta`` — a two-slot stand-in that avoids
    materializing ~1.6k StructuredTools just to embed their descriptions.
    """

    name: str
    description: str


class IndexedToolEntry(TypedDict):
    """One entry of the current/existing tool maps the diff runs over.

    Keyed by ``"<namespace>::<tool_name>"``. ``tool`` is present for real tools
    and ``description`` for subagent entries — ``_build_put_operations``
    discriminates on which one is there; rows read back from Chroma carry
    neither, since only the hash matters for the diff.
    """

    hash: str
    namespace: str
    tool: NotRequired[IndexableTool]
    description: NotRequired[str]


def _namespace_equals(namespace: str) -> Where:
    """A ``Where`` clause matching one namespace.

    The filter itself is correct — chromadb\'s own ``validate_where`` accepts it
    (and rejects a bogus operator, so that check is not a no-op), and running it
    against a live collection returns exactly the matching namespace\'s rows. The
    ``cast`` is purely a stub limitation: chromadb\'s ``Where`` alias allows bare
    ``str`` for field names but keys the operator dict by ``Literal["$eq", ...]``,
    so mypy widens the nested literal to ``dict[str, str]`` and rejects it. Keeping
    it in one helper confines the unchecked spot instead of spreading it over
    three call sites.
    """
    return cast(Where, {"namespace": {"$eq": namespace}})


def _compute_tool_hash(tool: IndexableTool) -> str:
    """Compute hash for a tool based on description and source code."""
    try:
        # inspect.getsource's stub only accepts module/class/function/etc, not an
        # arbitrary BaseTool instance; at runtime this virtually always raises
        # TypeError (caught below) since tool objects aren't source-inspectable,
        # so this call falls through to the name/description hash in practice.
        code_source = inspect.getsource(cast(Callable[..., Any], tool))
        code_source = code_source.strip()
        code_source = "\n".join(line.rstrip() for line in code_source.split("\n"))
        content = f"{tool.description}::{code_source}"
    except (OSError, TypeError, AttributeError):
        log.debug(
            f"{LogTag.CHROMA} Source unavailable for tool, using description hash",
            tool_name=getattr(tool, "name", "unknown"),
        )
        content = f"{tool.name}::{tool.description}"

    return hashlib.sha256(content.encode()).hexdigest()


def _get_current_tools_with_hashes(
    tool_registry: ToolRegistry,
) -> dict[str, IndexedToolEntry]:
    """Get all current tools with their hashes and namespaces.

    Args:
        tool_registry: Tool registry instance

    Returns:
        Dictionary mapping composite keys (namespace::tool_name) to their hash and namespace info.
        Composite keys prevent collisions when different namespaces have same-named tools.
    """
    current_tools: dict[str, IndexedToolEntry] = {}
    tool_dict = tool_registry.get_tool_dict()

    # Add regular tools
    for tool_name, tool in tool_dict.items():
        tool_hash = _compute_tool_hash(tool)

        tool_category = tool_registry.get_category(
            name=tool_registry.get_category_of_tool(tool.name)
        )
        if tool_category:
            composite_key = f"{tool_category.space}::{tool_name}"
            current_tools[composite_key] = IndexedToolEntry(
                hash=tool_hash, namespace=tool_category.space, tool=tool
            )

    # Add subagent tools
    subagent_tools = _get_subagent_tools()
    current_tools.update(subagent_tools)

    return current_tools


def _get_subagent_tools() -> dict[str, IndexedToolEntry]:
    """Get subagent tools with their hashes.

    Returns:
        Dictionary mapping subagent tool names to their hash and namespace info
    """
    subagent_tools: dict[str, IndexedToolEntry] = {}

    for subagent in all_subagents():
        cfg = subagent.config
        provider_name = subagent.name
        short_name = subagent.short_name or subagent.id

        # Create comprehensive description matching handoff_tools pattern
        description = (
            f"{provider_name} ({short_name}). "
            f"{provider_name} specializes in {cfg.domain}. "
            f"Use {provider_name} for: {cfg.use_cases}. "
            f"{provider_name} capabilities: {cfg.capabilities}"
        )

        # Compute hash based on description only
        subagent_hash = hashlib.sha256(description.encode()).hexdigest()

        subagent_tools[f"subagents::subagent:{subagent.id}"] = IndexedToolEntry(
            hash=subagent_hash, namespace="subagents", description=description
        )

    return subagent_tools


async def _get_existing_tools_from_chroma(
    collection: AsyncCollection, namespaces: set[str] | None = None
) -> dict[str, IndexedToolEntry]:
    """Fetch existing tools from ChromaDB collection.

    Args:
        collection: ChromaDB collection instance
        namespaces: Optional set of namespaces to filter by. If None, returns all.

    Returns:
        Dictionary mapping composite keys (namespace::tool_name) to their hash
        and namespace info. Composite keys prevent collisions when different
        namespaces have same-named tools.
    """
    existing_tools: dict[str, IndexedToolEntry] = {}

    try:
        # Use ChromaDB where filter for efficient namespace filtering
        where_filter: Where | None = None
        if namespaces is not None:
            ns_list = list(namespaces)
            if len(ns_list) == 1:
                where_filter = _namespace_equals(ns_list[0])
            elif len(ns_list) > 1:
                where_filter = {"$or": [_namespace_equals(ns) for ns in ns_list]}
            else:
                return existing_tools

        existing_data = (
            await collection.get(include=["metadatas"], where=where_filter)
            if where_filter
            else await collection.get(include=["metadatas"])
        )
        if existing_data and existing_data.get("ids") and existing_data.get("metadatas"):
            for doc_id, metadata in zip(existing_data["ids"], existing_data["metadatas"] or []):
                if metadata and "::" in doc_id:
                    parts = doc_id.split("::")
                    namespace = parts[0] if len(parts) > 1 else "default"

                    # Use full doc_id as composite key to prevent collisions
                    existing_tools[doc_id] = IndexedToolEntry(
                        hash=str(metadata.get("tool_hash", "")),
                        namespace=namespace,
                    )
    except Exception as e:
        log.warning(
            f"{LogTag.CHROMA} Error fetching existing tools, will register all tools",
            error=str(e),
            error_type=type(e).__name__,
        )

    return existing_tools


def _compute_tool_diff(
    current_tools: dict[str, IndexedToolEntry], existing_tools: dict[str, IndexedToolEntry]
) -> tuple[list[tuple[str, IndexedToolEntry]], list[tuple[str, str]]]:
    """Compute the difference between current and existing tools.

    Args:
        current_tools: Dictionary of current tools with hashes
        existing_tools: Dictionary of existing tool hashes and namespaces

    Returns:
        Tuple of (tools_to_upsert, tools_to_delete)
    """
    tools_to_upsert: list[tuple[str, IndexedToolEntry]] = []
    tools_to_delete: list[tuple[str, str]] = []

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
    tools_to_upsert: list[tuple[str, IndexedToolEntry]],
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
    put_ops: list[PutOp] = []

    # Add upsert operations
    for composite_key, tool_data in tools_to_upsert:
        # Extract actual tool name from composite key (namespace::tool_name)
        tool_name = composite_key.split("::", 1)[-1] if "::" in composite_key else composite_key

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
        tool_name = composite_key.split("::", 1)[-1] if "::" in composite_key else composite_key
        put_ops.append(
            PutOp(
                namespace=(namespace,),
                key=tool_name,
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
        log.info(
            f"{LogTag.CHROMA} Processed batch",
            batch_index=i // batch_size + 1,
            batch_total=(total_ops + batch_size - 1) // batch_size,
        )

    log.info(f"{LogTag.CHROMA} Successfully updated tools in ChromaDB", total_ops=total_ops)


async def index_tools_to_store(tools_with_space: Sequence[tuple[IndexableTool, str]]) -> None:
    """Index tools into ChromaDB store on-demand with full diff logic.

    This function manages tools for a specific namespace:
    1. Checks Redis cache to skip if tools haven't changed
    2. Fetches existing tools from ChromaDB for the namespace
    3. Compares with new tools to determine upsert/delete operations
    4. Removes stale tools, adds/updates new tools

    Args:
        tools_with_space: List of (tool, space_name) tuples to index
    """
    input_count = len(tools_with_space)
    namespace = tools_with_space[0][1] if tools_with_space else None

    log.set(
        vector=VectorContext(
            operation="upsert",
            collection="langgraph_tools_store",
        )
    )
    log.info(
        f"{LogTag.CHROMA} index_tools_to_store called",
        namespace=namespace,
        input_count=input_count,
    )

    if not tools_with_space:
        log.warning(
            f"{LogTag.CHROMA} index_tools_to_store called with EMPTY tools_with_space — caller "
            "passed [], no indexing will occur. Verify category.tools is populated."
        )
        return

    # Function assumes a homogeneous namespace (used as the cache key and for
    # diff scoping). Mixed namespaces would silently corrupt indexing for all
    # but the first one. Reject and surface the caller bug.
    distinct_namespaces = {space for _, space in tools_with_space}
    if len(distinct_namespaces) > 1:
        log.error(
            f"{LogTag.CHROMA} index_tools_to_store: mixed namespaces in single call; aborting to prevent partial indexing — caller must batch per-namespace",
            namespaces=sorted(distinct_namespaces),
        )
        return

    if not namespace or len(namespace) > 512 or "::" in namespace:
        log.error(
            f"{LogTag.CHROMA} index_tools_to_store: invalid namespace (empty/too-long/contains-::), aborting",
            namespace=namespace,
        )
        return

    # Compute hash of incoming tools for cache check
    tools_signature = "|".join(
        f"{t.name}:{getattr(t, 'description', '')[:200]}" for t, _ in tools_with_space
    )
    tools_hash = hashlib.sha256(tools_signature.encode()).hexdigest()[:16]

    # Single source of truth for cache keys: always namespace-based. The hash is
    # read here but CANNOT short-circuit on its own — see the verified check below.
    cache_key = f"chroma:indexed:{namespace}"
    cached_hash = await get_cache(cache_key)

    raw_store = await providers.aget("chroma_tools_store")
    if raw_store is None:
        log.warning(
            f"{LogTag.CHROMA} index_tools_to_store: provider returned None for namespace, skipping tools",
            namespace=namespace,
            input_count=input_count,
        )
        return

    # providers.aget declares -> Any | None; this provider is registered by
    # initialize_chroma_tools_store below, which always returns a ChromaStore.
    store = cast(ChromaStore, raw_store)
    collection = await store._get_collection()

    current_tools: dict[str, IndexedToolEntry] = {}
    for tool, space in tools_with_space:
        tool_hash = _compute_tool_hash(tool)
        composite_key = f"{space}::{tool.name}"
        current_tools[composite_key] = IndexedToolEntry(hash=tool_hash, namespace=space, tool=tool)
    log.info(
        f"{LogTag.CHROMA} index_tools_to_store: built current_tools dict of unique composite keys",
        namespace=namespace,
        current_tools_count=len(current_tools),
        input_count=input_count,
    )

    existing_tools = await _get_existing_tools_from_chroma(collection, {namespace})
    log.info(
        f"{LogTag.CHROMA} index_tools_to_store: fetched existing docs for namespace",
        existing_tools_count=len(existing_tools),
        namespace=namespace,
    )

    # The Redis hash only proves some past process BELIEVED it indexed this
    # namespace — never that ChromaDB still holds the docs. Trusting it alone made
    # a wiped/recreated Chroma permanent: the guard hit forever, the namespace was
    # never re-indexed, and tool discovery silently returned nothing. Require both.
    if cached_hash == tools_hash and existing_tools:
        log.info(
            f"{LogTag.CHROMA} index_tools_to_store: namespace cache HIT (verified against store), skipping reindex",
            namespace=namespace,
            tools_hash=tools_hash,
            input_count=input_count,
        )
        return
    if cached_hash == tools_hash and not existing_tools:
        log.warning(
            f"{LogTag.CHROMA} index_tools_to_store: Redis says namespace is indexed but ChromaDB holds 0 docs — store was wiped behind the cache; reindexing",
            namespace=namespace,
            input_count=input_count,
        )

    tools_to_upsert, tools_to_delete = _compute_tool_diff(current_tools, existing_tools)
    log.set_ns("vector", embedded_count=len(tools_to_upsert))

    if not tools_to_upsert and not tools_to_delete:
        log.info(
            f"{LogTag.CHROMA} index_tools_to_store: namespace is up-to-date ( tools, no diff)",
            namespace=namespace,
            current_tools_count=len(current_tools),
        )
        # Cache the hash even if no changes (first time seeing this namespace)
        await set_cache(cache_key, tools_hash, ttl=86400)
        return

    log.info(
        f"{LogTag.CHROMA} index_tools_to_store: Updating namespace : to upsert, to delete",
        namespace=namespace,
        tools_to_upsert_count=len(tools_to_upsert),
        tools_to_delete_count=len(tools_to_delete),
    )

    put_ops = _build_put_operations(tools_to_upsert, tools_to_delete)
    await _execute_batch_operations(store, put_ops)

    # Cache the hash after successful indexing (24 hour TTL)
    await set_cache(cache_key, tools_hash, ttl=86400)
    log.info(
        f"{LogTag.CHROMA} index_tools_to_store: completed namespace, cache key set",
        namespace=namespace,
    )


async def delete_tools_by_namespace(namespace: str) -> int:
    """Delete all tools indexed under a specific namespace.

    Used when a custom integration is deleted to clean up its tools from ChromaDB.

    Args:
        namespace: The namespace to delete tools from (e.g., URL domain)

    Returns:
        Number of tools deleted
    """

    log.set(vector=VectorContext(operation="delete", collection="langgraph_tools_store"))

    raw_store = await providers.aget("chroma_tools_store")
    if not raw_store:
        log.warning(f"{LogTag.CHROMA} ChromaDB store not available for cleanup")
        return 0

    store = cast(ChromaStore, raw_store)
    collection = await store._get_collection()

    # Use ChromaDB metadata filter to avoid a full collection scan.
    results = await collection.get(where=_namespace_equals(namespace), include=[])
    ids_to_delete = results.get("ids", [])
    log.set_ns("vector", result_count=len(ids_to_delete))

    if ids_to_delete:
        await collection.delete(ids=ids_to_delete)
        log.info(
            f"{LogTag.CHROMA} Deleted tools from namespace",
            ids_to_delete_count=len(ids_to_delete),
            namespace=namespace,
        )

    # Invalidate Redis cache for this namespace (unified format)
    await delete_cache(f"chroma:indexed:{namespace}")

    return len(ids_to_delete)


@lazy_provider(
    name="chroma_tools_store",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=False,  # Lazy-load only when first accessed (avoids duplicate indexing)
)
async def initialize_chroma_tools_store() -> ChromaStore:
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
    raw_embeddings = await providers.aget("google_embeddings")

    if raw_embeddings is None:
        raise RuntimeError("Embeddings not available")

    # Registered by init_embeddings() in app/agents/tools/core/store.py.
    embeddings = cast(GoogleGenerativeAIEmbeddings, raw_embeddings)

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

    current_tools = _get_current_tools_with_hashes(tool_registry)

    managed_namespaces = {tool_data["namespace"] for tool_data in current_tools.values()}
    log.set(vector=VectorContext(operation="upsert", collection="langgraph_tools_store"))
    log.info(f"{LogTag.CHROMA} Managing namespaces at init", managed_namespaces=managed_namespaces)

    existing_tools = await _get_existing_tools_from_chroma(collection, managed_namespaces)

    tools_to_upsert, tools_to_delete = _compute_tool_diff(current_tools, existing_tools)
    log.set_ns("vector", embedded_count=len(tools_to_upsert))

    if not tools_to_upsert and not tools_to_delete:
        log.info(f"{LogTag.CHROMA} ChromaDB tools store is up-to-date, no changes needed")
        return store

    log.info(
        f"{LogTag.CHROMA} Updating ChromaDB tools store: to upsert, to delete",
        tools_to_upsert_count=len(tools_to_upsert),
        tools_to_delete_count=len(tools_to_delete),
    )

    put_ops = _build_put_operations(tools_to_upsert, tools_to_delete)
    await _execute_batch_operations(store, put_ops)

    return store
