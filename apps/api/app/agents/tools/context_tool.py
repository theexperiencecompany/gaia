"""Gather context from all connected integrations for a specific date.

Calls each integration's CUSTOM_GATHER_CONTEXT tool in parallel via Composio.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from app.utils.context_utils import fetch_all_providers, resolve_providers
from app.services.composio.custom_tools.context_tool import (
    PROVIDER_TOOLS,
    tool_namespace,
)
from app.templates.docstrings.context_tool_docs import GATHER_CONTEXT_DOC
from app.utils.chat_utils import get_user_id_from_config
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
@with_doc(GATHER_CONTEXT_DOC)
async def gather_context(
    config: RunnableConfig,
    providers: Annotated[
        Optional[List[str]],
        "Specific providers to query (calendar, gmail, linear, slack, notion, github, google_tasks, todoist, asana, trello, clickup, hubspot, teams, google_docs, google_sheets, airtable, google_maps, google_meet, instagram, linkedin, reddit, twitter). If None, auto-detects connected.",
    ] = None,
    date: Annotated[
        Optional[str],
        "Target date in YYYY-MM-DD format. Defaults to today.",
    ] = None,
) -> Dict[str, Any]:
    """Gather context from all connected providers in parallel."""
    start_time = time.time()
    user_id = get_user_id_from_config(config)
    if not user_id:
        return {"error": "User authentication required", "data": None}

    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Resolve which providers to query
    resolved_providers = await resolve_providers(
        providers, user_id, PROVIDER_TOOLS, tool_namespace
    )

    # Fetch in parallel (sync function run in executor to avoid blocking event loop)
    loop = asyncio.get_running_loop()
    context_results = await loop.run_in_executor(
        None,
        fetch_all_providers,
        resolved_providers,
        PROVIDER_TOOLS,
        user_id,
    )

    total_time = time.time() - start_time
    logger.info(
        f"Context fetched from {len(resolved_providers)} providers in {total_time:.2f}s"
    )

    return {
        "date": date_str,
        "providers_queried": list(context_results.keys()),
        "context": context_results,
        "_performance": {
            "total_time_seconds": round(total_time, 2),
            "providers_attempted": len(resolved_providers),
            "providers_succeeded": len(context_results),
        },
    }
