"""Tests for PostgreSQL database layer: engine init, session management, shutdown.

Covers:
- init_postgresql_engine: URL rewriting, engine creation, table creation
- get_postgresql_engine: provider retrieval, RuntimeError on None
- get_db_session: context manager yield, session close
- close_postgresql_db: disposal when initialized, error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.postgresql import (
    Base,
    close_postgresql_db,
    get_db_session,
    get_postgresql_engine,
    init_postgresql_engine,
)


def _get_original_init_fn():
    """Extract the original async function wrapped by @lazy_provider.

    The decorator replaces the function with ``register_provider`` — a closure
    whose ``__wrapped__`` attribute is not set.  The original coroutine function
    is captured in the closure and can be retrieved from the providers registry
    after calling the registration helper once.
    """
    from app.core.lazy_loader import providers

    # Calling the decorated name triggers registration and returns a LazyLoader
    if not providers.is_available("postgresql_engine"):
        try:
            init_postgresql_engine()
        except Exception:
            pass
    try:
        loader = providers.get_loader("postgresql_engine")
        return loader.loader_func
    except KeyError:
        # Force registration
        init_postgresql_engine()
        loader = providers.get_loader("postgresql_engine")
        return loader.loader_func


# ---------------------------------------------------------------------------
# get_postgresql_engine
# ---------------------------------------------------------------------------


class TestGetPostgresqlEngine:
    """Tests for get_postgresql_engine()."""

    async def test_returns_engine_from_provider(self) -> None:
        """Should return the engine when the provider resolves successfully."""
        mock_engine = MagicMock()

        with patch(
            "app.db.postgresql.providers.aget",
            new_callable=AsyncMock,
            return_value=mock_engine,
        ):
            result = await get_postgresql_engine()

        assert result is mock_engine

    async def test_raises_runtime_error_when_none(self) -> None:
        """Should raise RuntimeError when provider returns None."""
        with patch(
            "app.db.postgresql.providers.aget",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="not available"):
                await get_postgresql_engine()

    async def test_passes_correct_provider_name(self) -> None:
        """Should request the 'postgresql_engine' provider by name."""
        mock_engine = MagicMock()

        with patch(
            "app.db.postgresql.providers.aget",
            new_callable=AsyncMock,
            return_value=mock_engine,
        ) as mock_aget:
            await get_postgresql_engine()

        mock_aget.assert_awaited_once_with("postgresql_engine")


# ---------------------------------------------------------------------------
# get_db_session
# ---------------------------------------------------------------------------


class TestGetDbSession:
    """Tests for the get_db_session() async context manager."""

    async def test_yields_session_and_closes(self) -> None:
        """Should yield an AsyncSession and close it after the block."""
        mock_engine = MagicMock()
        mock_session = AsyncMock()

        with (
            patch(
                "app.db.postgresql.get_postgresql_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("app.db.postgresql.AsyncSession") as mock_session_cls,
        ):
            # AsyncSession as context manager
            mock_session_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            async with get_db_session() as session:
                assert session is mock_session

            mock_session.close.assert_awaited_once()

    async def test_closes_session_on_exception(self) -> None:
        """Session should be closed even if an exception occurs in the block."""
        mock_engine = MagicMock()
        mock_session = AsyncMock()

        with (
            patch(
                "app.db.postgresql.get_postgresql_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("app.db.postgresql.AsyncSession") as mock_session_cls,
        ):
            mock_session_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="test error"):
                async with get_db_session():
                    raise ValueError("test error")

            mock_session.close.assert_awaited_once()

    async def test_propagates_engine_error(self) -> None:
        """If get_postgresql_engine raises, it should propagate."""
        with patch(
            "app.db.postgresql.get_postgresql_engine",
            new_callable=AsyncMock,
            side_effect=RuntimeError("engine unavailable"),
        ):
            with pytest.raises(RuntimeError, match="engine unavailable"):
                async with get_db_session():
                    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# close_postgresql_db
# ---------------------------------------------------------------------------


class TestClosePostgresqlDb:
    """Tests for close_postgresql_db() shutdown function."""

    async def test_disposes_engine_when_initialized(self) -> None:
        """When PostgreSQL is initialized, should dispose the engine."""
        mock_engine = AsyncMock()

        with (
            patch("app.db.postgresql.providers.is_initialized", return_value=True),
            patch(
                "app.db.postgresql.get_postgresql_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("app.db.postgresql.log") as mock_log,
        ):
            await close_postgresql_db()

        mock_engine.dispose.assert_awaited_once()
        mock_log.info.assert_called()

    async def test_skips_disposal_when_not_initialized(self) -> None:
        """When PostgreSQL was never initialized, should do nothing."""
        with (
            patch("app.db.postgresql.providers.is_initialized", return_value=False),
            patch(
                "app.db.postgresql.get_postgresql_engine",
                new_callable=AsyncMock,
            ) as mock_get,
            patch("app.db.postgresql.log"),
        ):
            await close_postgresql_db()

        mock_get.assert_not_awaited()

    async def test_logs_error_on_disposal_exception(self) -> None:
        """If engine.dispose() raises, should log the error."""
        mock_engine = AsyncMock()
        mock_engine.dispose.side_effect = RuntimeError("dispose failed")

        with (
            patch("app.db.postgresql.providers.is_initialized", return_value=True),
            patch(
                "app.db.postgresql.get_postgresql_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("app.db.postgresql.log") as mock_log,
        ):
            # Should not raise
            await close_postgresql_db()

        mock_log.error.assert_called_once()
        assert "dispose failed" in mock_log.error.call_args[0][0]


# ---------------------------------------------------------------------------
# init_postgresql_engine (decorated function)
# ---------------------------------------------------------------------------


class TestInitPostgresqlEngine:
    """Tests for the init_postgresql_engine() lazy provider function."""

    async def test_url_rewriting_postgresql_to_asyncpg(self) -> None:
        """Should rewrite 'postgresql://' to 'postgresql+asyncpg://' in the URL."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin.return_value = mock_ctx

        with (
            patch("app.db.postgresql.settings") as mock_settings,
            patch(
                "app.db.postgresql.create_async_engine", return_value=mock_engine
            ) as mock_create,
            patch("app.db.postgresql.log"),
        ):
            mock_settings.POSTGRES_URL = "postgresql://user:pass@host:5432/db"

            result = await _get_original_init_fn()()

            # Verify the URL was rewritten
            call_kwargs = mock_create.call_args
            assert "postgresql+asyncpg://" in call_kwargs.kwargs.get(
                "url", call_kwargs.args[0] if call_kwargs.args else ""
            )
            assert result is mock_engine

    async def test_creates_tables_on_init(self) -> None:
        """Should run Base.metadata.create_all during initialization."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin.return_value = mock_ctx

        with (
            patch("app.db.postgresql.settings") as mock_settings,
            patch("app.db.postgresql.create_async_engine", return_value=mock_engine),
            patch("app.db.postgresql.log"),
        ):
            mock_settings.POSTGRES_URL = "postgresql://localhost/test"

            await _get_original_init_fn()()

            mock_conn.run_sync.assert_awaited_once()

    async def test_engine_pool_configuration(self) -> None:
        """Engine should be created with expected pool settings."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin.return_value = mock_ctx

        with (
            patch("app.db.postgresql.settings") as mock_settings,
            patch(
                "app.db.postgresql.create_async_engine", return_value=mock_engine
            ) as mock_create,
            patch("app.db.postgresql.log"),
        ):
            mock_settings.POSTGRES_URL = "postgresql://localhost/test"

            await _get_original_init_fn()()

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["future"] is True
            assert call_kwargs["pool_pre_ping"] is True
            assert call_kwargs["pool_size"] == 5
            assert call_kwargs["max_overflow"] == 10

    async def test_url_already_asyncpg_not_double_rewritten(self) -> None:
        """If URL already uses asyncpg, the replace should still work correctly."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin.return_value = mock_ctx

        with (
            patch("app.db.postgresql.settings") as mock_settings,
            patch(
                "app.db.postgresql.create_async_engine", return_value=mock_engine
            ) as mock_create,
            patch("app.db.postgresql.log"),
        ):
            # URL that doesn't have plain "postgresql://" won't be rewritten
            mock_settings.POSTGRES_URL = "postgresql+asyncpg://host/db"

            await _get_original_init_fn()()

            call_kwargs = mock_create.call_args
            url = call_kwargs.kwargs.get("url", "")
            # Should not have double +asyncpg
            assert "asyncpg+asyncpg" not in url


# ---------------------------------------------------------------------------
# Base declarative model
# ---------------------------------------------------------------------------


class TestBaseDeclarativeModel:
    """Tests for the SQLAlchemy Base."""

    def test_base_exists(self) -> None:
        """Base should be a declarative base for defining ORM models."""
        assert Base is not None
        assert hasattr(Base, "metadata")
