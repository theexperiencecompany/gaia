"""Airtable tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.airtable import AirtableBase, AirtableBaseList, AirtableBaseSchema
from app.models.integrations.composio import CustomToolAuthCredentials
from app.utils.context_utils import execute_tool
from shared.py.wide_events import log


def register_airtable_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        bases_raw: list[AirtableBase] = []
        try:
            bases_raw = AirtableBaseList.model_validate(
                execute_tool("AIRTABLE_LIST_BASES", {}, user_id)
            ).bases
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Airtable bases fetch failed", error_type=type(e).__name__)

        bases: list[dict[str, object]] = []
        for base in bases_raw[:3]:
            tables: list[dict[str, str]] = []
            try:
                schema = AirtableBaseSchema.model_validate(
                    execute_tool(
                        "AIRTABLE_GET_BASE_SCHEMA",
                        {"base_id": base.id},
                        user_id,
                    )
                )
                tables = [{"id": t.id, "name": t.name} for t in schema.tables]
            except Exception as e:
                log.debug(
                    f"{LogTag.TOOL} Airtable tables fetch failed",
                    base_id=base.id,
                    error_type=type(e).__name__,
                )
            bases.append({"id": base.id, "name": base.name, "tables": tables})

        return {"bases": bases, "base_count": len(bases_raw)}

    return ["AIRTABLE_CUSTOM_GATHER_CONTEXT"]
