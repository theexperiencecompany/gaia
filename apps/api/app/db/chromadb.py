from typing import Optional

import chromadb
from app.config.loggers import chroma_logger as logger
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from chromadb.api import AsyncClientAPI
from chromadb.config import Settings
from fastapi import Request
from langchain_chroma import Chroma


class ChromaClient:
    """
    Simple proxy for ChromaDB clients that delegates to lazy providers.
    This class provides access to:
    1. The raw AsyncClientAPI client for direct ChromaDB interactions
    2. The Langchain Chroma client for vector search integrations
    3. Collection-specific Langchain clients via dynamically created providers
    """

    @classmethod
    async def get_client(cls, request: Optional[Request] = None) -> AsyncClientAPI:
        """
        Get the ChromaDB client from the application state or from lazy providers.

        Args:
            request: The FastAPI request object

        Returns:
            The ChromaDB client

        Raises:
            RuntimeError: If ChromaDB client is not available
        """
        # Get the client from the lazy provider
        try:
            client = await providers.aget("chromadb_client")
            if client is None:
                raise RuntimeError("ChromaDB client could not be initialized")
            return client
        except Exception as e:
            logger.error(f"Failed to get ChromaDB client: {e}")
            raise RuntimeError("ChromaDB client not initialized") from e

    @classmethod
    async def get_langchain_client(
        cls,
        collection_name: Optional[str] = None,
        embedding_function=None,
        create_if_not_exists: bool = True,
    ) -> Chroma:
        """
        Get a langchain Chroma client for a specific collection.

        Args:
            collection_name: The name of the collection to connect to. If None, returns the default client.
            embedding_function: Optional embedding function to use with the client.
                               If None, the default embedding model will be used.
            create_if_not_exists: Whether to create the collection if it doesn't exist.

        Returns:
            The langchain Chroma client for the specified collection

        Raises:
            RuntimeError: If langchain Chroma client is not available
        """
        # Ensure we have the embedding function
        if embedding_function is None:
            embedding_function = await providers.aget("google_embeddings")

        # If no collection name provided, return the default client
        if not collection_name:
            default_client = await providers.aget("langchain_chroma")
            if default_client is None:
                raise RuntimeError("Default Langchain Chroma client not initialized")
            return default_client

        # Build a unique provider name for this collection
        provider_name = f"langchain_chroma_{collection_name}"

        # If provider already exists, return it
        existing = providers.is_initialized(provider_name)

        if existing:
            instance = await providers.aget(provider_name)
            if instance is None:
                raise RuntimeError(
                    f"Failed to retrieve existing Langchain client for collection '{collection_name}'"
                )
            return instance  # type: ignore

        # Dynamically register a provider for this collection and auto-initialize it
        async def _loader() -> Chroma:
            logger.debug(
                f"Creating Langchain client for collection '{collection_name}' via provider '{provider_name}'"
            )
            constructor_client = await providers.aget("chromadb_constructor")
            if not constructor_client:
                raise RuntimeError("ChromaDB constructor client not initialized")

            # Ensure the collection exists using the synchronous constructor client
            try:
                collections = constructor_client.list_collections()  # type: ignore[attr-defined]
                existing_names = [c.name for c in collections]  # type: ignore
            except Exception:
                existing_names = []

            if collection_name not in existing_names:
                if not create_if_not_exists:
                    raise RuntimeError(f"Collection '{collection_name}' not found")
                constructor_client.create_collection(  # type: ignore[attr-defined]
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )

            return Chroma(
                client=constructor_client,
                collection_name=collection_name,  # type: ignore[arg-type]
                embedding_function=embedding_function,
            )

        providers.register(
            name=provider_name,
            loader_func=_loader,  # type: ignore[arg-type]
            required_keys=[settings.CHROMADB_HOST, settings.CHROMADB_PORT],
            strategy=MissingKeyStrategy.ERROR,
            auto_initialize=True,
        )

        instance = await providers.aget(provider_name)
        if instance is None:
            raise RuntimeError(
                f"Failed to create Langchain client for collection '{collection_name}'"
            )
        return instance


@lazy_provider(
    name="chromadb_client",
    required_keys=[
        settings.CHROMADB_HOST,
        settings.CHROMADB_PORT,
    ],
    auto_initialize=False,
    strategy=MissingKeyStrategy.WARN,
)
async def init_chromadb_client():
    """
    Initialize ChromaDB async client.

    Returns:
        AsyncClientAPI: The ChromaDB async client
    """
    host: str = settings.CHROMADB_HOST  # type: ignore
    port: int = settings.CHROMADB_PORT  # type: ignore

    # Initialize ChromaDB async http client
    client = await chromadb.AsyncHttpClient(
        host=host,
        port=port,
    )

    response = await client.heartbeat()
    logger.debug(f"ChromaDB heartbeat response: {response}")
    logger.info(f"Connected to ChromaDB at {host}:{port}")

    # Create default collections if they don't exist
    existing_collections = await client.list_collections()
    existing_collection_names = [col.name for col in existing_collections]  # type: ignore
    collection_names = ["notes", "documents"]

    # Create collections if they don't exist
    for collection_name in collection_names:
        if collection_name not in existing_collection_names:
            logger.debug(f"Creating collection '{collection_name}'")
            await client.create_collection(
                name=collection_name, metadata={"hnsw:space": "cosine"}
            )
            logger.debug(f"Collection '{collection_name}' created")
        else:
            logger.debug(f"Collection '{collection_name}' exists")

    return client


@lazy_provider(
    name="chromadb_constructor",
    required_keys=[
        settings.CHROMADB_HOST,
        settings.CHROMADB_PORT,
    ],
    auto_initialize=False,
    strategy=MissingKeyStrategy.WARN,
)
def init_chromadb_constructor():
    """
    Initialize ChromaDB constructor client for langchain.
    This is a workaround to avoid the `coroutine` error in langchain
    when using the async client directly.

    Returns:
        ClientAPI: The ChromaDB constructor client
    """
    logger.debug("Initializing ChromaDB constructor client")

    host: str = settings.CHROMADB_HOST  # type: ignore
    port: int = settings.CHROMADB_PORT  # type: ignore

    # Initialize ChromaDB client for langchain
    constructor_client = chromadb.Client(
        settings=Settings(
            chroma_server_host=host,
            chroma_server_http_port=port,
        )
    )

    return constructor_client


@lazy_provider(
    name="langchain_chroma",
    required_keys=[
        settings.CHROMADB_HOST,
        settings.CHROMADB_PORT,
    ],
    auto_initialize=False,
    strategy=MissingKeyStrategy.WARN,
)
def init_langchain_chroma():
    """
    Initialize default Langchain Chroma client.

    Returns:
        Chroma: The default Langchain Chroma client
    """
    logger.debug("Initializing default Langchain Chroma client")

    # Get the constructor client
    constructor_client = providers.get("chromadb_constructor")
    if not constructor_client:
        raise RuntimeError("ChromaDB constructor client not initialized")

    # Create default langchain client with no specific collection
    langchain_chroma_client = Chroma(
        client=constructor_client,
        embedding_function=providers.get("google_embeddings"),
    )

    return langchain_chroma_client


def init_chroma():
    """
    Backward compatibility function to initialize ChromaDB client and store in app state.
    This is mainly for compatibility with existing code that calls init_chroma explicitly.

    In new code, prefer using ChromaClient.get_client() directly which lazily initializes.

    Args:
        app: FastAPI application instance

    Returns:
        The ChromaDB client
    """
    try:
        init_chromadb_client()
        init_chromadb_constructor()
        init_langchain_chroma()

    except Exception as e:
        logger.error(f"Error in init_chroma compatibility function: {e}")
        raise RuntimeError(f"ChromaDB connection failed: {e}") from e
