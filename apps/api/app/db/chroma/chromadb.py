from typing import cast

import chromadb
from chromadb.api import AsyncClientAPI, ClientAPI
from chromadb.config import Settings
from fastapi import Request
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.chroma.noop_telemetry import NOOP_PRODUCT_TELEMETRY_IMPL
from shared.py.wide_events import log


class ChromaClient:
    """
    Simple proxy for ChromaDB clients that delegates to lazy providers.
    This class provides access to:
    1. The raw AsyncClientAPI client for direct ChromaDB interactions
    2. The Langchain Chroma client for vector search integrations
    3. Collection-specific Langchain clients via dynamically created providers
    """

    @classmethod
    async def get_client(
        cls,
        request: Request | None = None,
    ) -> AsyncClientAPI:
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
            # aget() is typed Any | None; "chromadb_client" is always registered
            # via init_chromadb_client(), which returns AsyncClientAPI.
            return cast(AsyncClientAPI, client)
        except Exception as e:
            log.error(
                f"{LogTag.CHROMA} Failed to get ChromaDB client",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise RuntimeError("ChromaDB client not initialized") from e

    @classmethod
    async def get_langchain_client(
        cls,
        collection_name: str | None = None,
        embedding_function: Embeddings | None = None,
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
            # aget() is typed Any | None; "langchain_chroma" is always registered
            # as a Chroma instance.
            return cast(Chroma, default_client)

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
            return cast(Chroma, instance)

        # Dynamically register a provider for this collection and auto-initialize it
        async def _loader() -> Chroma:
            log.debug(
                f"{LogTag.CHROMA} Creating Langchain client for collection via provider",
                collection_name=collection_name,
                provider_name=provider_name,
            )
            constructor_client = await providers.aget("chromadb_constructor")
            if not constructor_client:
                raise RuntimeError("ChromaDB constructor client not initialized")

            # Ensure the collection exists using the synchronous constructor client
            try:
                collections = constructor_client.list_collections()
                existing_names = [c.name for c in collections]
            except Exception:
                existing_names = []

            if collection_name not in existing_names:
                if not create_if_not_exists:
                    raise RuntimeError(f"Collection '{collection_name}' not found")
                constructor_client.create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )

            return Chroma(
                client=constructor_client,
                collection_name=collection_name,
                embedding_function=embedding_function,
            )

        providers.register(
            name=provider_name,
            loader_func=_loader,  # type: ignore[arg-type]  # langchain’s collection-loader callback param is untyped upstream
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
async def init_chromadb_client() -> AsyncClientAPI:
    """
    Initialize ChromaDB async client.

    Returns:
        AsyncClientAPI: The ChromaDB async client
    """
    host: str = settings.CHROMADB_HOST
    port: int = settings.CHROMADB_PORT

    # Route telemetry to a no-op client (see NoopProductTelemetry): the bundled
    # posthog telemetry is incompatible with the installed posthog and errors on
    # every collection op.
    client = await chromadb.AsyncHttpClient(
        host=host,
        port=port,
        settings=Settings(
            chroma_product_telemetry_impl=NOOP_PRODUCT_TELEMETRY_IMPL,
            chroma_telemetry_impl=NOOP_PRODUCT_TELEMETRY_IMPL,
        ),
    )

    response = await client.heartbeat()
    log.debug(f"{LogTag.CHROMA} ChromaDB heartbeat response", response=response)
    log.set(
        db={
            "connection_status": "connected",
            "backend": "chromadb",
            "host": host,
            "port": port,
        }
    )
    log.info(f"{LogTag.CHROMA} Connected to ChromaDB at", host=host, port=port)

    # Create default collections if they don't exist
    existing_collections = await client.list_collections()
    existing_collection_names = [col.name for col in existing_collections]
    collection_names = ["notes", "documents", "gaia_canvas"]

    # Create collections if they don't exist
    for collection_name in collection_names:
        if collection_name not in existing_collection_names:
            log.debug(f"{LogTag.CHROMA} Creating collection", collection_name=collection_name)
            await client.create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
            log.debug(f"{LogTag.CHROMA} Collection created", collection_name=collection_name)
        else:
            log.debug(f"{LogTag.CHROMA} Collection exists", collection_name=collection_name)

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
def init_chromadb_constructor() -> ClientAPI:
    """
    Initialize ChromaDB constructor client for langchain.
    This is a workaround to avoid the `coroutine` error in langchain
    when using the async client directly.

    Returns:
        ClientAPI: The ChromaDB constructor client
    """
    log.debug(f"{LogTag.CHROMA} Initializing ChromaDB constructor client")

    host: str = settings.CHROMADB_HOST
    port: int = settings.CHROMADB_PORT

    # HttpClient, NOT Client: only HttpClient sets chroma_api_impl to the FastAPI
    # backend. chromadb.Client() keeps the default RustBindingsAPI with
    # is_persistent=False and never reads chroma_server_host/port, so passing
    # them in Settings built a process-local in-memory store that silently
    # answered its own reads while nothing ever reached the server — every
    # collection written through this client (documents, notes, gaia_canvas)
    # sat at zero rows on the server while looking healthy in-process.
    # Telemetry off for the same reason as init_chromadb_client.
    constructor_client = chromadb.HttpClient(
        host=host,
        port=port,
        settings=Settings(
            chroma_product_telemetry_impl=NOOP_PRODUCT_TELEMETRY_IMPL,
            chroma_telemetry_impl=NOOP_PRODUCT_TELEMETRY_IMPL,
        ),
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
def init_langchain_chroma() -> Chroma:
    """
    Initialize default Langchain Chroma client.

    Returns:
        Chroma: The default Langchain Chroma client
    """
    log.debug(f"{LogTag.CHROMA} Initializing default Langchain Chroma client")

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


def init_chroma() -> None:
    """
    Backward compatibility function to initialize ChromaDB client and store in app state.
    This is mainly for compatibility with existing code that calls init_chroma explicitly.

    In new code, prefer using ChromaClient.get_client() directly which lazily initializes.
    """
    try:
        init_chromadb_client()
        init_chromadb_constructor()
        init_langchain_chroma()

    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error in init_chroma compatibility function",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise RuntimeError(f"ChromaDB connection failed: {e}") from e
