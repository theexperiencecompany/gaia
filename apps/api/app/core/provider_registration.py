"""Unified startup/shutdown for FastAPI and the ARQ worker.

This module does two distinct things:

1) Registers lazy providers.
   Provider registration is always fast and should happen on every process start.

2) Initializes services.

   - In development, we initialize services during startup so problems surface
     immediately and reload cycles are predictable.

   - In production (FastAPI only), we intentionally *do not block startup* on
     initialization. Instead, we schedule the same initialization coroutines in
     the background so the server can begin accepting traffic quickly.

Gotchas:
- Background warmup failures do not crash the server; they are logged.
- While warmup is running, request handlers may still call `providers.aget(...)`.
  This is safe: `LazyLoader` uses per-provider locks so concurrent calls join
  the same initialization work rather than double-initializing.
- Always use `providers.aget(...)` for async providers; `providers.get(...)`
  is only for sync providers.
"""

import asyncio
import warnings
from collections.abc import Awaitable, Callable
from typing import Literal

from app.agents.core.graph_builder.build_graph import build_graphs
from app.agents.core.graph_builder.checkpointer_manager import init_checkpointer_manager
from app.agents.llm.client import register_llm_providers
from app.agents.tools.core.registry import init_tool_registry
from app.agents.tools.core.store import init_embeddings
from app.config.cloudinary import init_cloudinary
from app.config.loggers import app_logger as logger
from app.config.opik import init_opik
from app.config.posthog import init_posthog
from app.config.settings import settings
from app.constants.startup import (
    AUTO_PROVIDER_CONCURRENCY,
    PROD_PROVIDER_WARMUP_CONCURRENCY,
)
from app.core.lazy_loader import providers
from app.db.chroma.chroma_tools_store import initialize_chroma_tools_store
from app.db.chroma.chroma_triggers_store import initialize_chroma_triggers_store
from app.db.chroma.chromadb import init_chroma
from app.db.postgresql import init_postgresql_engine
from app.db.rabbitmq import init_rabbitmq_publisher
from app.helpers.lifespan_helpers import (
    _process_results,
    close_checkpointer_manager,
    close_mcp_client_pool,
    close_postgresql_async,
    close_publisher_async,
    close_reminder_scheduler,
    close_websocket_async,
    close_workflow_scheduler,
    init_mongodb_async,
    init_reminder_service,
    init_websocket_consumer,
    init_workflow_service,
)
from app.services.composio.composio_service import init_composio_service
from app.services.mcp.mcp_client_pool import init_mcp_client_pool
from app.services.startup_validation import validate_startup_requirements
from app.services.tools.tools_warmup import warmup_tools_cache
from app.services.vfs import get_vfs, init_vfs
from pydantic import PydanticDeprecatedSince20


def setup_warnings() -> None:
    """Set up common warning filters."""
    warnings.filterwarnings(
        "ignore", category=PydanticDeprecatedSince20, module="langchain_core.tools.base"
    )


setup_warnings()


_background_tasks: list[asyncio.Task] = []


def _spawn_background_task(
    name: str,
    coro_factory: Callable[[], Awaitable[object]],
) -> None:
    """Schedule a background init task without blocking startup.

    Implementation detail:
    - We create an `asyncio.Task` immediately. Task execution only progresses
      once the event loop gets control again, so this does not block startup.
    - We track created tasks so shutdown can cancel them.
    """

    async def _runner() -> None:
        logger.info(f"Background init started: {name}")
        try:
            await coro_factory()
            logger.info(f"Background init finished: {name}")
        except asyncio.CancelledError:
            logger.info(f"Background init cancelled: {name}")
            raise
        except Exception as e:
            logger.error(f"Background init failed: {name}: {e}")

    task = asyncio.create_task(_runner(), name=f"warmup:{name}")
    _background_tasks.append(task)


def _spawn_background_services(
    services: list[tuple[Callable[[], Awaitable[object]], str]],
    *,
    name: str = "startup_warmup",
    after: Callable[[], Awaitable[object]] | None = None,
    after_name: str | None = None,
) -> None:
    """Schedule multiple service coroutines in a single background task.

    We intentionally run these as one task (instead of one task per service) so:
    - logs are easier to follow
    - shutdown only needs to cancel one warmup task
    - we get a single place to aggregate failures
    """

    async def _run_all() -> None:
        startup_tasks = [service_func() for service_func, _ in services]
        service_names = [service_name for _, service_name in services]

        results = await asyncio.gather(*startup_tasks, return_exceptions=True)

        failed = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed += 1
                logger.error(f"Background init failed ({service_names[i]}): {result}")

        if failed:
            logger.warning(
                f"Background init completed with {failed}/{len(services)} failures"
            )
        else:
            logger.info(f"Background init completed: {len(services)} services")

        if after is not None:
            followup_name = after_name or "followup"
            logger.info(f"Background init started: {followup_name}")
            try:
                await after()
                logger.info(f"Background init finished: {followup_name}")
            except asyncio.CancelledError:
                logger.info(f"Background init cancelled: {followup_name}")
                raise
            except Exception as e:
                logger.error(f"Background init failed: {followup_name}: {e}")

    _spawn_background_task(name, _run_all)


async def unified_startup(context: Literal["main_app", "arq_worker"]) -> None:
    """
    Unified startup function for both FastAPI and ARQ worker contexts.

    Handles complete initialization flow:
    1. Lazy provider registration (databases, AI models, tools)
    2. Context-specific eager service initialization
    3. Parallel execution with error handling

    Args:
        context: "main_app" for FastAPI, "arq_worker" for background tasks

    Raises:
        RuntimeError: If any critical service fails to initialize
    """
    logger.info(f"Starting {context} with unified provider system...")

    # Register lazy providers (dormant until first access).
    #
    # Gotcha: many providers are authored as `async def` and decorated with
    # `@lazy_provider(...)`. The decorator replaces the async function with a
    # sync registration function, so these calls are intentionally NOT awaited.
    logger.info(f"Registering lazy providers for {context}...")

    registrations: tuple[Callable[[], object], ...] = (
        init_postgresql_engine,
        init_rabbitmq_publisher,
        register_llm_providers,
        build_graphs,
        init_chroma,
        init_checkpointer_manager,
        init_tool_registry,
        init_composio_service,
        init_mcp_client_pool,
        init_embeddings,
        initialize_chroma_tools_store,
        initialize_chroma_triggers_store,
        init_cloudinary,
        validate_startup_requirements,
        init_vfs,
        init_posthog,
        init_opik,
    )

    for register in registrations:
        register()
    logger.info(f"All lazy providers registered successfully for {context}")

    # Services we typically want running in-process.
    #
    # In development and in the ARQ worker we initialize these during startup.
    # In production FastAPI we schedule them to initialize in the background.
    eager_services = [
        (init_mongodb_async, "mongodb"),
        (init_reminder_service, "reminder_service"),
        (init_workflow_service, "workflow_service"),
        (get_vfs, "vfs"),
    ]

    # Context-specific services: WebSocket only needed for web interface
    if context == "main_app":
        eager_services.append((init_websocket_consumer, "websocket_consumer"))

    startup_services: list[tuple[Callable[[], Awaitable[object]], str]] = list(
        eager_services
    )
    startup_services.append(
        (
            lambda: providers.initialize_auto_providers(
                concurrency=AUTO_PROVIDER_CONCURRENCY,
                strict=False,
            ),
            "lazy_providers_auto_initializer",
        )
    )
    startup_services.append((warmup_tools_cache, "tools_cache_warmup"))

    # Production FastAPI: start serving quickly, warm up in background.
    if context == "main_app" and settings.ENV == "production":
        logger.info(
            "Production mode: scheduling warmup tasks in background "
            "(non-blocking startup)"
        )

        _spawn_background_services(
            startup_services,
            after=lambda: providers.warmup_all(
                concurrency=PROD_PROVIDER_WARMUP_CONCURRENCY,
                strict=False,
            ),
            after_name="lazy_providers_warmup_all",
        )
        return

    # Build parallel execution tasks (faster startup via concurrency)
    startup_tasks = [service_func() for service_func, _ in startup_services]
    service_names = [service_name for _, service_name in startup_services]

    try:
        # Execute all tasks in parallel (return_exceptions prevents cascade failures)
        results = await asyncio.gather(*startup_tasks, return_exceptions=True)
        _process_results(results, service_names)  # Validate results and handle failures

        logger.info(f"All {context} services initialized successfully")
        logger.info(f"{context.title().replace('_', ' ')} startup complete")

    except Exception as e:
        logger.error(f"Error during {context} startup: {e}")
        raise RuntimeError(f"{context} startup failed") from e


async def unified_shutdown(context: Literal["main_app", "arq_worker"]) -> None:
    """
    Unified shutdown function for both FastAPI and ARQ worker contexts.

    Performs graceful cleanup:
    1. Context-specific service selection
    2. Parallel cleanup execution
    3. Isolated error handling (one failure doesn't stop others)

    Args:
        context: "main_app" for FastAPI, "arq_worker" for background tasks
    """
    logger.info(f"Shutting down {context}...")

    # Cancel any background warmup tasks first.
    if _background_tasks:
        logger.info(f"Cancelling {len(_background_tasks)} background tasks")
        for task in list(_background_tasks):
            if not task.done():
                task.cancel()
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()

    # Define cleanup services (context-aware resource management)
    # Base cleanup needed by both contexts
    shutdown_services = [
        (close_postgresql_async, "postgresql"),
        (close_reminder_scheduler, "reminder_scheduler"),
        (close_workflow_scheduler, "workflow_scheduler"),
        (close_checkpointer_manager, "checkpointer_manager"),
        (close_mcp_client_pool, "mcp_client_pool"),
    ]

    # Context-specific cleanup: additional services only for FastAPI
    if context == "main_app":
        shutdown_services.extend(
            [
                (close_websocket_async, "websocket"),  # WebSocket event consumer
                (close_publisher_async, "publisher"),  # Message queue publisher
            ]
        )

    if not shutdown_services:
        logger.info(f"No shutdown tasks for {context}")
        return

    # Build parallel cleanup tasks (faster shutdown via concurrency)
    shutdown_tasks = [shutdown_func() for shutdown_func, _ in shutdown_services]
    shutdown_service_names = [service_name for _, service_name in shutdown_services]

    try:
        # Execute cleanup in parallel with isolated error handling
        # return_exceptions=True ensures one failure doesn't block other cleanups
        shutdown_results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        # Log failures without stopping other cleanup operations
        for i, result in enumerate(shutdown_results):
            if isinstance(result, Exception):
                logger.error(
                    f"Error during {context} {shutdown_service_names[i]} shutdown: {result}"
                )

        logger.info(f"{context} services shutdown completed")

    except Exception as e:
        logger.error(f"Error during {context} shutdown: {e}")

    logger.info(f"{context} shutdown complete")
