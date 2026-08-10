"""Airtable tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from app.utils.json_helpers import list_bag, text_bag, text_opt_bag
from shared.py.wide_events import log


def register_airtable_custom_tools(composio: Composio[Any, Any]) -> list[str]:
    """Register Airtable tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="AIRTABLE")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Airtable context snapshot: bases (workspaces) and their tables.

        Zero required parameters. Returns current workspace structure for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "airtable", "action": "gather_context"})
        user_id = text_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        bases_raw: list[dict[str, object]] = []
        try:
            data = execute_tool("AIRTABLE_LIST_BASES", {}, user_id)
            bases_raw = [b for b in list_bag(data, "bases") if isinstance(b, dict)]
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Airtable bases fetch failed", error_type=type(e).__name__)

        bases: list[dict[str, object]] = []
        for base in bases_raw[:3]:
            base_id = text_bag(base, "id")
            tables: list[dict[str, object]] = []
            try:
                schema_data = execute_tool(
                    "AIRTABLE_GET_BASE_SCHEMA",
                    {"base_id": base_id},
                    user_id,
                )
                tables = [
                    {"id": text_opt_bag(t, "id"), "name": text_opt_bag(t, "name")}
                    for t in list_bag(schema_data, "tables")
                    if isinstance(t, dict)
                ]
            except Exception as e:
                log.debug(
                    f"{LogTag.TOOL} Airtable tables fetch failed",
                    base_id=base_id,
                    error_type=type(e).__name__,
                )
            bases.append({"id": base_id, "name": text_bag(base, "name"), "tables": tables})

        return {"bases": bases, "base_count": len(bases_raw)}

    return ["AIRTABLE_CUSTOM_GATHER_CONTEXT"]
