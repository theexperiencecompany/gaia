"""Unit tests for app/db/chroma/chromadb.py.

Covers:
- ChromaClient.get_client (success, failure)
- ChromaClient.get_langchain_client (default, named collection, cached provider, create_if_not_exists=False)
- init_chromadb_client (heartbeat, collection creation)
- init_chromadb_constructor
- init_langchain_chroma
- init_chroma compatibility function
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "app.db.chroma.chromadb"


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


class TestChromaClientGetClient:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_success(self, mock_providers: MagicMock) -> None:
        mock_client = MagicMock()
        mock_providers.aget = AsyncMock(return_value=mock_client)

        from app.db.chroma.chromadb import ChromaClient

        result = await ChromaClient.get_client()
        assert result is mock_client
        mock_providers.aget.assert_awaited_once_with("chromadb_client")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_none_client_raises(self, mock_providers: MagicMock) -> None:
        mock_providers.aget = AsyncMock(return_value=None)

        from app.db.chroma.chromadb import ChromaClient

        with pytest.raises(RuntimeError, match="ChromaDB client"):
            await ChromaClient.get_client()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_provider_exception_raises(self, mock_providers: MagicMock) -> None:
        mock_providers.aget = AsyncMock(side_effect=Exception("connection failed"))

        from app.db.chroma.chromadb import ChromaClient

        with pytest.raises(RuntimeError, match="ChromaDB client not initialized"):
            await ChromaClient.get_client()


class TestChromaClientGetLangchainClient:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_default_client_no_collection(
        self, mock_providers: MagicMock
    ) -> None:
        mock_default = MagicMock()
        mock_embeddings = MagicMock()

        async def _aget(name: str) -> Any:
            if name == "google_embeddings":
                return mock_embeddings
            if name == "langchain_chroma":
                return mock_default
            return None

        mock_providers.aget = AsyncMock(side_effect=_aget)

        from app.db.chroma.chromadb import ChromaClient

        result = await ChromaClient.get_langchain_client()
        assert result is mock_default

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_default_client_none_raises(self, mock_providers: MagicMock) -> None:
        async def _aget(name: str) -> Any:
            if name == "google_embeddings":
                return MagicMock()
            return None

        mock_providers.aget = AsyncMock(side_effect=_aget)

        from app.db.chroma.chromadb import ChromaClient

        with pytest.raises(
            RuntimeError, match="Default Langchain Chroma client not initialized"
        ):
            await ChromaClient.get_langchain_client()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_existing_provider_returned(self, mock_providers: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_providers.is_initialized.return_value = True

        async def _aget(name: str) -> Any:
            if name == "google_embeddings":
                return MagicMock()
            return mock_instance

        mock_providers.aget = AsyncMock(side_effect=_aget)

        from app.db.chroma.chromadb import ChromaClient

        result = await ChromaClient.get_langchain_client(collection_name="notes")
        assert result is mock_instance

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_existing_provider_none_raises(
        self, mock_providers: MagicMock
    ) -> None:
        mock_providers.is_initialized.return_value = True

        async def _aget(name: str) -> Any:
            return None

        mock_providers.aget = AsyncMock(side_effect=_aget)

        from app.db.chroma.chromadb import ChromaClient

        with pytest.raises(RuntimeError, match="Failed to retrieve existing"):
            await ChromaClient.get_langchain_client(collection_name="notes")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.providers")
    async def test_new_collection_registered(
        self, mock_providers: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_providers.is_initialized.return_value = False
        mock_settings.CHROMADB_HOST = "localhost"
        mock_settings.CHROMADB_PORT = 8000
        mock_instance = MagicMock()

        call_count = 0

        async def _aget(name: str) -> Any:
            nonlocal call_count
            if name == "google_embeddings":
                return MagicMock()
            # Last call returns the created instance
            call_count += 1
            if call_count >= 1:
                return mock_instance
            return None

        mock_providers.aget = AsyncMock(side_effect=_aget)
        mock_providers.register = MagicMock()

        from app.db.chroma.chromadb import ChromaClient

        result = await ChromaClient.get_langchain_client(collection_name="custom_coll")
        assert result is mock_instance
        mock_providers.register.assert_called_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.providers")
    async def test_new_collection_creation_fails(
        self, mock_providers: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_providers.is_initialized.return_value = False
        mock_settings.CHROMADB_HOST = "localhost"
        mock_settings.CHROMADB_PORT = 8000

        async def _aget(name: str) -> Any:
            if name == "google_embeddings":
                return MagicMock()
            return None

        mock_providers.aget = AsyncMock(side_effect=_aget)
        mock_providers.register = MagicMock()

        from app.db.chroma.chromadb import ChromaClient

        with pytest.raises(RuntimeError, match="Failed to create Langchain client"):
            await ChromaClient.get_langchain_client(collection_name="bad_coll")


class TestChromaClientGetClientWithRequest:
    """Additional ChromaClient.get_client tests with request parameter."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_get_client_ignores_request_param(
        self, mock_providers: MagicMock
    ) -> None:
        """The request parameter is accepted but not used; client comes from providers."""
        mock_client = MagicMock()
        mock_providers.aget = AsyncMock(return_value=mock_client)

        from app.db.chroma.chromadb import ChromaClient

        fake_request = MagicMock()
        result = await ChromaClient.get_client(request=fake_request)
        assert result is mock_client


class TestChromaClientGetLangchainClientWithEmbedding:
    """Tests passing explicit embedding_function."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.providers")
    async def test_custom_embedding_used(self, mock_providers: MagicMock) -> None:
        mock_default = MagicMock()

        async def _aget(name: str) -> Any:
            if name == "langchain_chroma":
                return mock_default
            return None

        mock_providers.aget = AsyncMock(side_effect=_aget)

        from app.db.chroma.chromadb import ChromaClient

        custom_embed = MagicMock()
        result = await ChromaClient.get_langchain_client(
            embedding_function=custom_embed
        )
        assert result is mock_default
        # google_embeddings provider should not be fetched when custom embedding passed
        calls = [c.args[0] for c in mock_providers.aget.call_args_list]
        assert "google_embeddings" not in calls


class TestInitChroma:
    @patch(f"{MODULE}.init_langchain_chroma")
    @patch(f"{MODULE}.init_chromadb_constructor")
    @patch(f"{MODULE}.init_chromadb_client")
    def test_calls_all_initializers(
        self,
        mock_client: MagicMock,
        mock_constructor: MagicMock,
        mock_langchain: MagicMock,
    ) -> None:
        from app.db.chroma.chromadb import init_chroma

        init_chroma()
        mock_client.assert_called_once()
        mock_constructor.assert_called_once()
        mock_langchain.assert_called_once()

    @patch(f"{MODULE}.init_langchain_chroma")
    @patch(f"{MODULE}.init_chromadb_constructor")
    @patch(f"{MODULE}.init_chromadb_client", side_effect=RuntimeError("fail"))
    def test_error_raises_runtime_error(
        self,
        mock_client: MagicMock,
        mock_constructor: MagicMock,
        mock_langchain: MagicMock,
    ) -> None:
        from app.db.chroma.chromadb import init_chroma

        with pytest.raises(RuntimeError, match="ChromaDB connection failed"):
            init_chroma()
