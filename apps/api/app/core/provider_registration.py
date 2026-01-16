"""
Unified service initialization system for FastAPI and ARQ worker contexts.

This module provides streamlined startup and shutdown functions that handle:
- Lazy provider registration (databases, AI models, tools, etc.)
- Context-aware eager service initialization (different services for web vs worker)
- Parallel execution with proper error handling
- Graceful shutdown with resource cleanup

Usage:
    # FastAPI lifespan
    await unified_startup("main_app")
    await unified_shutdown("main_app")

    # ARQ worker lifecycle
    await unified_startup("arq_worker")
    await unified_shutdown("arq_worker")
"""

import asyncio
import warnings
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
from app.core.lazy_loader import providers
from app.db.chroma.chroma_tools_store import initialize_chroma_tools_store
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
    # setup_event_loop_policy,
)
from app.services.composio.composio_service import init_composio_service
from app.services.mcp.mcp_client_pool import init_mcp_client_pool
from app.services.startup_validation import validate_startup_requirements
from app.services.tools.tools_warmup import warmup_tools_cache
from pydantic import PydanticDeprecatedSince20


def setup_warnings() -> None:
    """Set up common warning filters."""
    warnings.filterwarnings(
        "ignore", category=PydanticDeprecatedSince20, module="langchain_core.tools.base"
    )


setup_warnings()


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

    # Register lazy providers (dormant until first access)
    # These set up factory functions but don't connect to services yet
    logger.info(f"Registering lazy providers for {context}...")
    init_postgresql_engine()
    init_rabbitmq_publisher()
    register_llm_providers()
    build_graphs()
    init_chroma()
    init_checkpointer_manager()
    init_tool_registry()
    init_composio_service()
    init_mcp_client_pool()
    init_embeddings()
    initialize_chroma_tools_store()
    init_cloudinary()
    validate_startup_requirements()
    # setup_event_loop_policy()
    init_posthog()
    init_opik()
    logger.info(f"All lazy providers registered successfully for {context}")

    # Define eager services (must be ready before processing requests/tasks)
    # Base services needed by both FastAPI and ARQ worker
    eager_services = [
        (init_mongodb_async, "mongodb"),
        (init_reminder_service, "reminder_service"),
        (init_workflow_service, "workflow_service"),
    ]

    # Context-specific services: WebSocket only needed for web interface
    if context == "main_app":
        eager_services.append((init_websocket_consumer, "websocket_consumer"))

    # Build parallel execution tasks (faster startup via concurrency)
    startup_tasks = [service_func() for service_func, _ in eager_services]
    service_names = [service_name for _, service_name in eager_services]

    # Add auto-initialization of providers marked with auto_initialize=True
    startup_tasks.append(providers.initialize_auto_providers())
    service_names.append("lazy_providers_auto_initializer")

    # Warm up tools cache (loads provider tools and pre-caches global tools response)
    startup_tasks.append(warmup_tools_cache())
    service_names.append("tools_cache_warmup")

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
