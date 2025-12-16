"""
Evaluation-specific provider initialization.

Registers and initializes only the providers required for running subagent evaluations.
This is lighter than full backend startup (build_graphs, websockets, etc.).

Usage:
    from app.agents.evals.initialization import init_eval_providers
    await init_eval_providers(subagent_ids=["github", "gmail"])
"""

from typing import Optional

from app.agents.core.subagents.provider_subagents import register_subagent_providers
from app.agents.llm.client import register_llm_providers
from app.agents.tools.core.registry import init_tool_registry
from app.agents.tools.core.store import init_embeddings
from app.config.loggers import app_logger as logger
from app.config.posthog import init_posthog
from app.core.lazy_loader import providers
from app.db.chromadb.chroma_tools_store import initialize_chroma_tools_store
from app.db.chromadb.chromadb import init_chroma
from app.db.postgresql import init_postgresql_engine
from app.services.composio.composio_service import init_composio_service


async def init_eval_providers(subagent_ids: Optional[list[str]] = None) -> None:
    """
    Initialize providers required for subagent evaluation.

    Unlike full backend startup, this skips:
    - MongoDB
    - RabbitMQ
    - WebSocket consumers
    - Workflow/Reminder schedulers
    - Full graph building

    Args:
        subagent_ids: Optional list of specific subagent IDs to load.
                     If None, registers all subagents but doesn't eagerly load them.
    """
    logger.info("Registering eval-specific lazy providers...")

    # Register lazy providers (dormant until first access)
    init_postgresql_engine()
    register_llm_providers()
    init_chroma()
    init_tool_registry()
    init_composio_service()
    init_embeddings()
    init_posthog()
    initialize_chroma_tools_store()

    # Register subagents - either specific ones or all
    register_subagent_providers(subagent_ids)

    logger.info("All eval lazy providers registered")

    # Initialize providers that need eager loading
    await providers.initialize_auto_providers()

    logger.info("Eval providers initialized successfully")
