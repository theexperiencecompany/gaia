import asyncio

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.utils.embedding_utils import get_or_compute_embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.memory import InMemoryStore


@lazy_provider(
    name="google_embeddings",
    required_keys=[settings.GOOGLE_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
    warning_message="Embeddings not configured. Tool discovery using tool_retrieval tool will fail. "
    "Sometimes agent calls tool_retrieval for tool discovery. This may lead to errors when agent is invoked.",
)
def init_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    embeddings = providers.get("google_embeddings")
    if embeddings is None:
        raise RuntimeError("Embeddings not available")
    return embeddings


@lazy_provider(
    name="tools_store",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=False,
)
async def initialize_tools_store():
    """Initialize and return the tool registry and store.

    Returns:
        tuple: A tuple containing the tool registry and the store.
    """
    # Lazy import to avoid circular dependency
    from app.agents.tools.core.registry import get_tool_registry

    tool_registry = await get_tool_registry()

    # Register both regular and always available tools
    tool_dict = tool_registry.get_tool_dict()
    all_tools = [tool_data for tool_data in tool_dict.values()]

    embeddings = get_embeddings()

    # Store all tools for vector search with cached embeddings
    embeddings_list, tool_descriptions = await get_or_compute_embeddings(
        all_tools, embeddings
    )

    store = InMemoryStore(
        index={
            "embed": embeddings,
            "dims": 768,
            "fields": ["description"],
        }
    )

    # Build tasks for batch storage with pre-computed embeddings
    tasks = []
    for i, tool in enumerate(tool_dict.values()):
        tool_category = tool_registry.get_category(
            name=tool_registry.get_category_of_tool(tool.name)
        )

        if not tool_category:
            continue

        # Use aput with pre-computed embeddings for proper space handling
        tasks.append(
            store.aput(
                (tool_category.space,),
                tool.name,
                {
                    "description": tool_descriptions[i],
                    "embedding": embeddings_list[i],
                },
            )
        )

    # Store all tools using asyncio batch with proper space structure
    await asyncio.gather(*tasks)

    return store


async def get_tools_store() -> InMemoryStore:
    tools_store = await providers.aget("tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    return tools_store
