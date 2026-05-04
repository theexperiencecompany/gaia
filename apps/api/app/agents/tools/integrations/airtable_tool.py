"""Airtable tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

from composio import Composio

from shared.py.wide_events import log
from app.agents.tools.core.toolkit_manifest import (
    ToolManifestEntry,
    ToolkitManifest,
    ToolOutputField,
)
from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_airtable_custom_tools(composio: Composio) -> List[str]:
    """Register Airtable tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="AIRTABLE")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Airtable context snapshot: bases (workspaces) and their tables.

        Zero required parameters. Returns current workspace structure for situational awareness.
        """
        log.set(tool={"integration": "airtable", "action": "gather_context"})
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        bases_raw: List[Dict[str, Any]] = []
        try:
            data = execute_tool("AIRTABLE_LIST_BASES", {}, user_id)
            bases_raw = data.get("bases", [])
        except Exception as e:
            log.debug(f"Airtable bases fetch failed: {e}")

        bases: List[Dict[str, Any]] = []
        for base in bases_raw[:3]:
            base_id = base.get("id", "")
            tables: List[Dict[str, Any]] = []
            try:
                schema_data = execute_tool(
                    "AIRTABLE_GET_BASE_SCHEMA",
                    {"base_id": base_id},
                    user_id,
                )
                tables = [
                    {"id": t.get("id"), "name": t.get("name")}
                    for t in schema_data.get("tables", [])
                ]
            except Exception as e:
                log.debug(f"Airtable tables fetch for {base_id} failed: {e}")
            bases.append(
                {"id": base_id, "name": base.get("name", ""), "tables": tables}
            )

        return {"bases": bases, "base_count": len(bases_raw)}

    return ["AIRTABLE_CUSTOM_GATHER_CONTEXT"]


MANIFEST = ToolkitManifest(
    toolkit="airtable",
    tools={
        "AIRTABLE_CUSTOM_GATHER_CONTEXT": ToolManifestEntry(
            description="Snapshot of Airtable bases (workspaces) and their tables.",
            outputs=[
                ToolOutputField("bases", "list[dict]", "Up to 3 bases, each with id, name, and tables list (id, name per table)"),
                ToolOutputField("base_count", "int", "Total number of bases in the account"),
            ],
        ),
    },
)
