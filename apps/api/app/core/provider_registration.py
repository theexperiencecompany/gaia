"""Unified startup/shutdown for FastAPI and the ARQ worker.

Registers lazy providers (fast, every process start), then initializes
services: blocking during startup when hot reloading is enabled, or
scheduled in the background otherwise so the server can start serving quickly.

Background warmup failures are logged, not fatal. LazyLoader's per-provider
locks let a request handler safely call providers.aget(...) concurrently with
warmup instead of double-initializing. Use providers.aget(...) for async
providers; providers.get(...) is sync-only.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal
import warnings

from pydantic import PydanticDeprecatedSince20

from app.agents.core.graph_builder.build_graph import build_graphs
from app.agents.core.graph_builder.checkpointer_manager import init_checkpointer_manager
from app.agents.llm.client import register_llm_providers
from app.agents.llm.model_catalog import init_openrouter_model_catalog
from app.agents.tools.core.registry import init_tool_registry
from app.agents.tools.core.store import init_embeddings
from app.config.cloudinary import init_cloudinary
from app.config.langfuse import init_langfuse
from app.config.posthog import init_posthog
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.startup import (
    AUTO_PROVIDER_CONCURRENCY,
    PROD_PROVIDER_WARMUP_CONCURRENCY,
)
from app.core.lazy_loader import providers
from app.db.chroma.chroma_tools_store import initialize_chroma_tools_store
from app.db.chroma.chroma_triggers_store import initialize_chroma_triggers_store
from app.db.chroma.chromadb import init_chroma
from app.db.postgresql import init_postgresql_engine
from app.db.rabbitmq import declare_outbound_topology_on_startup, init_rabbitmq_publisher
from app.db.redis import redis_cache
from app.helpers.lifespan_helpers import (
    StartupService,
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
    init_websocket_broadcast_listener,
    init_workflow_service,
)
from app.services.composio.composio_service import init_composio_service
from app.services.mcp.mcp_client_pool import init_mcp_client_pool
from app.services.sandbox.pool import init_sandbox_pool
from app.services.startup_validation import validate_startup_requirements
from app.services.storage.bootstrap import init_juicefs_mount
from app.services.tools.tools_warmup import warmup_tools_cache
from app.services.workspace_sync import init_system_subtree, resync_stale_user_workspaces
from app.utils.concurrency import capture_running_loop
from shared.py.wide_events import log, spawn_logged_task


def setup_warnings() -> None:
    """Set up common warning filters."""
    warnings.filterwarnings(
        "ignore", category=PydanticDeprecatedSince20, module="langchain_core.tools.base"
    )


setup_warnings()


# Warmup tasks are tracked so shutdown can cancel them. `spawn_logged_task`
# already keeps its own strong reference for GC safety and gives each task a
# wide-event boundary; this list exists purely for the cancel-on-shutdown pass.
_background_tasks: list[asyncio.Task] = []


def _spawn_background_services(
    services: list[StartupService],
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
        startup_tasks = [service.func() for service in services]
        service_names = [service.name for service in services]

        results = await asyncio.gather(*startup_tasks, return_exceptions=True)

        failed = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed += 1
                log.error(
                    f"{LogTag.STARTUP} Background init failed",
                    service_name=service_names[i],
                    error_type=type(result).__name__,
                )

        if failed:
            log.warning(
                f"{LogTag.STARTUP} Background init completed with / failures",
                failed=failed,
                services_count=len(services),
            )
        else:
            log.info(
                f"{LogTag.STARTUP} Background init completed: services",
                services_count=len(services),
            )

        if after is not None:
            followup_name = after_name or "followup"
            log.info(f"{LogTag.STARTUP} Background init started", followup_name=followup_name)
            try:
                await after()
                log.info(f"{LogTag.STARTUP} Background init finished", followup_name=followup_name)
            except asyncio.CancelledError:
                log.info(f"{LogTag.STARTUP} Background init cancelled", followup_name=followup_name)
                raise
            except Exception as e:
                log.error(
                    f"{LogTag.STARTUP} Background init failed",
                    followup_name=followup_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    _background_tasks.append(spawn_logged_task(name, _run_all()))


def register_lazy_providers(context: Literal["main_app", "arq_worker"]) -> None:
    """Register all lazy providers (dormant until first access).

    Fast, no I/O — safe on every process start. Split out from unified_startup
    so a test harness can populate the registry without full eager-service
    startup. Many providers are async def, but @lazy_provider wraps them in a
    sync registration function, so these calls aren't awaited.
    """
    log.info(f"{LogTag.STARTUP} Registering lazy providers for ...", context=context)

    registrations: tuple[Callable[[], object], ...] = (
        init_postgresql_engine,
        init_rabbitmq_publisher,
        register_llm_providers,
        init_openrouter_model_catalog,
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
        init_juicefs_mount,
        init_sandbox_pool,
        init_posthog,
        init_langfuse,
    )

    for register in registrations:
        register()
    log.info(f"{LogTag.STARTUP} All lazy providers registered successfully for", context=context)


async def unified_startup(context: Literal["main_app", "arq_worker"]) -> None:
    """Run the unified startup flow for FastAPI and the ARQ worker.

    Registers lazy providers, then initializes context-specific services in
    parallel; raises RuntimeError if a required service fails.
    """
    # Record the process role (main_app vs arq_worker) as observable config,
    # derived from the declared startup context so it can't drift from reality:
    # docker sets it via env, but native dev does not — leaving it "unknown".
    settings.WORKER_TYPE = context

    # Record this loop before any async client is built on it, so worker threads
    # (sync Composio custom tools) can dispatch coroutines back onto the loop the
    # Motor/Redis clients are bound to instead of spinning a fresh one.
    capture_running_loop()

    log.info(f"{LogTag.STARTUP} Starting with unified provider system...", context=context)

    register_lazy_providers(context)

    # In development and in the ARQ worker these initialize during startup;
    # in production FastAPI they're scheduled to initialize in the background.
    eager_services = [
        StartupService(init_mongodb_async, "mongodb", required=True),
        StartupService(redis_cache.verify_connection, "redis", required=True),
        StartupService(init_reminder_service, "reminder_service", required=True),
        StartupService(init_workflow_service, "workflow_service", required=True),
        # JuiceFS mount — best-effort: the provider is a no-op when R2/JFS settings
        # are unconfigured, and a storage-backend fault (R2 read errors) must degrade
        # file features, not crash the worker.
        StartupService(lambda: providers.aget("juicefs_mount"), "juicefs_mount", required=False),
        # Shared system subtree (INDEX/GUIDE/builtin skills) — best-effort optimization;
        # falls back to per-user copies. Awaits the mount internally.
        StartupService(init_system_subtree, "system_subtree", required=False),
    ]

    # Outbound bot-message queues must exist before any executor reply or
    # reminder is published — declared in both the API and the ARQ worker.
    eager_services.append(
        StartupService(declare_outbound_topology_on_startup, "outbound_topology", required=True)
    )

    # Context-specific services: only the web app holds user WebSockets, so only
    # it subscribes to the broadcast fan-out. Workers publish without subscribing.
    if context == "main_app":
        eager_services.append(
            StartupService(
                init_websocket_broadcast_listener, "websocket_broadcast_listener", required=True
            )
        )
        # Re-sync active users whose skill catalog is stale (deploy shipped new
        # skills). Detached so it never blocks boot; runs only in the web app.
        _background_tasks.append(
            spawn_logged_task("workspace_stale_resync", resync_stale_user_workspaces())
        )

    startup_services: list[StartupService] = list(eager_services)
    startup_services.append(
        StartupService(
            # strict=True + required=True let an ERROR-strategy provider (e.g.
            # tool_registry) abort a blocking boot instead of coming up broken;
            # warmup_all below stays lenient since the server is already serving.
            lambda: providers.initialize_auto_providers(
                concurrency=AUTO_PROVIDER_CONCURRENCY,
                strict=True,
            ),
            "lazy_providers_auto_initializer",
            required=True,
        )
    )
    startup_services.append(
        StartupService(warmup_tools_cache, "tools_cache_warmup", required=False)
    )

    # FastAPI with hot reloading disabled: start serving quickly,
    # warm up in background.
    if context == "main_app" and not settings.ENABLE_LAZY_LOADING:
        log.info(
            f"{LogTag.STARTUP} Hot reloading disabled: scheduling warmup tasks in background (non-blocking startup)"
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
    startup_tasks = [service.func() for service in startup_services]

    try:
        # Execute all tasks in parallel (return_exceptions prevents cascade failures)
        results = await asyncio.gather(*startup_tasks, return_exceptions=True)
        _process_results(
            results, startup_services
        )  # raise on required failures; degrade best-effort

        log.info(f"{LogTag.STARTUP} All services initialized successfully", context=context)
        log.info(f"{LogTag.STARTUP} Startup complete", context=context)

    except Exception as e:
        log.error(
            f"{LogTag.STARTUP} Error during startup",
            context=context,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise RuntimeError(f"{context} startup failed") from e


async def unified_shutdown(context: Literal["main_app", "arq_worker"]) -> None:
    """Run the unified shutdown flow for FastAPI and the ARQ worker.

    Cleans up context-specific services in parallel; one failure doesn't stop
    the others.
    """
    log.info(f"{LogTag.STARTUP} Shutting down ...", context=context)

    # Cancel any background warmup tasks first.
    if _background_tasks:
        log.info(
            f"{LogTag.STARTUP} Cancelling background tasks",
            _background_tasks_count=len(_background_tasks),
        )
        for task in _background_tasks:
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
        # Both contexts open a RabbitMQ connection at startup (outbound topology
        # declaration + publishing), so close the publisher unconditionally.
        (close_publisher_async, "publisher"),
    ]

    # Context-specific cleanup: the WebSocket event consumer only runs in FastAPI.
    if context == "main_app":
        shutdown_services.append((close_websocket_async, "websocket"))

    if not shutdown_services:
        log.info(f"{LogTag.STARTUP} No shutdown tasks for", context=context)
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
                log.error(
                    f"{LogTag.STARTUP} Error during service shutdown",
                    context=context,
                    service_name=shutdown_service_names[i],
                    error_type=type(result).__name__,
                )

        log.info(f"{LogTag.STARTUP} services shutdown completed", context=context)

    except Exception as e:
        log.error(
            f"{LogTag.STARTUP} Error during shutdown",
            context=context,
            error=str(e),
            error_type=type(e).__name__,
        )

    log.info(f"{LogTag.STARTUP} shutdown complete", context=context)
