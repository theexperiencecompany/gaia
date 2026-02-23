from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import BaseStore


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


async def get_tools_store() -> BaseStore:
    tools_store = await providers.aget("chroma_tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    return tools_store
