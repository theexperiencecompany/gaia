from collections.abc import Awaitable, Callable
from typing import NamedTuple

from app.core.lazy_loader import providers
from app.core.websocket_consumer import (
    start_websocket_consumer,
    stop_websocket_consumer,
)
from app.db.postgresql import close_postgresql_db
from app.db.rabbitmq import get_rabbitmq_publisher
from app.services.reminder_service import reminder_scheduler
from app.services.workflow.scheduler import workflow_scheduler
from shared.py.wide_events import log


async def init_reminder_service():
    """Initialize reminder scheduler and scan for pending reminders."""
    try:
        await reminder_scheduler.initialize()
        await reminder_scheduler.scan_and_schedule_pending_tasks()
        log.info("Reminder scheduler initialized and pending reminders scheduled")
    except Exception as e:
        log.error(f"Failed to initialize reminder scheduler: {e}")
        raise


async def init_workflow_service():
    """Initialize workflow service."""
    try:
        await workflow_scheduler.initialize()
        await workflow_scheduler.scan_and_schedule_pending_tasks()
        log.info("Workflow service initialized")
    except Exception as e:
        log.error(f"Failed to initialize workflow service: {e}")
        raise


async def init_websocket_consumer():
    """Initialize WebSocket event consumer."""
    try:
        await start_websocket_consumer()
        log.info("WebSocket event consumer started")
    except Exception as e:
        log.error(f"Failed to start WebSocket consumer: {e}")
        raise


async def init_mongodb_async():
    """Initialize MongoDB and create database indexes."""
    try:
        from app.db.mongodb.mongodb import init_mongodb

        mongo_client = init_mongodb()
        await mongo_client._initialize_indexes()
        log.info("MongoDB initialized and indexes created")
    except Exception as e:
        log.error(f"Failed to initialize MongoDB and create indexes: {e}")
        raise


# Shutdown methods
async def close_postgresql_async():
    """Close PostgreSQL database connection."""
    try:
        await close_postgresql_db()
        log.info("PostgreSQL database closed")
    except Exception as e:
        log.error(f"Error closing PostgreSQL database: {e}")


async def close_reminder_scheduler():
    """Close reminder scheduler."""
    try:
        from app.services.reminder_service import reminder_scheduler

        await reminder_scheduler.close()
        log.info("Reminder scheduler closed")
    except Exception as e:
        log.error(f"Error closing reminder scheduler: {e}")


async def close_workflow_scheduler():
    """Close workflow scheduler."""
    try:
        await workflow_scheduler.close()
        log.info("Workflow scheduler closed")
    except Exception as e:
        log.error(f"Error closing workflow scheduler: {e}")


async def close_websocket_async():
    """Close WebSocket event consumer."""
    try:
        await stop_websocket_consumer()
        log.info("WebSocket event consumer stopped")
    except Exception as e:
        log.error(f"Error stopping WebSocket consumer: {e}")


async def close_publisher_async():
    """Close publisher connection."""
    try:
        # Avoid initializing the publisher during shutdown.
        if not providers.is_initialized("rabbitmq_publisher"):
            return

        publisher = await get_rabbitmq_publisher()

        if publisher:
            await publisher.close()

        log.info("Publisher closed")
    except Exception as e:
        log.error(f"Error closing publisher: {e}")


async def close_checkpointer_manager():
    """Close checkpointer manager and connection pool."""
    try:
        # Avoid initializing the checkpointer during shutdown.
        if not providers.is_initialized("checkpointer_manager"):
            return

        checkpointer_manager = await providers.aget("checkpointer_manager")
        if checkpointer_manager:
            await checkpointer_manager.close()
            log.info("Checkpointer manager closed")
    except Exception as e:
        log.error(f"Error closing checkpointer manager: {e}")


async def close_mcp_client_pool():
    """Close MCP client pool and all active connections."""
    try:
        if providers.is_initialized("mcp_client_pool"):
            pool = await providers.aget("mcp_client_pool")
            if pool:
                await pool.shutdown()
                log.info("MCP client pool closed")
    except Exception as e:
        log.error(f"Error closing MCP client pool: {e}")


class StartupService(NamedTuple):
    """A startup coroutine plus whether its failure is fatal.

    ``required=True``  → failure aborts startup (Mongo, Redis, schedulers, outbound
    topology): the process is useless without it, so crashing is the honest signal.
    ``required=False`` → best-effort: optional infrastructure / optimizations the app
    degrades gracefully without (the JuiceFS mount, the shared system subtree, cache
    warmups). A storage-backend fault hitting one of these used to take down the whole
    ARQ worker; now it logs and the process keeps running. Criticality lives on the
    descriptor at its definition site so it can't drift from a separate lookup table.
    """

    func: Callable[[], Awaitable[object]]
    name: str
    required: bool = True


def _process_results(results: list[object], services: list[StartupService]) -> None:
    """Raise if any REQUIRED startup service failed; degrade (log) for best-effort ones.

    A best-effort service failing for ANY reason (not just I/O) is non-fatal. Required
    services still hard-fail so a genuine misconfiguration surfaces loudly instead of a
    half-initialized process.
    """
    required_failures = []
    for result, service in zip(results, services):
        if not isinstance(result, Exception):
            continue
        if service.required:
            required_failures.append(service.name)
            log.error(f"Failed to initialize {service.name}: {result}")
        else:
            log.warning(
                f"Best-effort startup service '{service.name}' failed; continuing degraded: {result}"
            )

    if required_failures:
        error_msg = f"Failed to initialize required services: {required_failures}"
        log.error(error_msg)
        raise RuntimeError(error_msg)
