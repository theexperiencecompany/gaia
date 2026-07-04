"""Classify whether a tool is destructive for the HIL approval gate.

Resolution order (first match wins):

1. Exempt orchestration/plumbing tools → safe.
2. The tool registry's ``destructive`` flag — authoritative for internal tools
   and curated integration slugs.
3. For unclassified (custom MCP) tools, a cached Mongo classification.
4. A one-shot LLM classification, written back to Mongo and the live registry.
5. Any failure or a tool absent from the registry → destructive (fail closed).
"""

import hashlib

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured
from app.agents.tools.core.registry import get_tool_registry
from app.constants.hil import HIL_EXEMPT_TOOLS
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import hil_tool_risk_collection
from app.models.hil_models import HILToolRiskRecord
from shared.py.wide_events import log

_CLASSIFY_PROMPT = (
    "An AI assistant may call the tool below autonomously on the user's behalf.\n"
    "Mark it destructive if executing it is irreversible or produces an effect "
    "visible to other people — sending, posting, deleting, or paying. Reading, "
    "searching, or fetching data is NOT destructive.\n\n"
    "Tool name: {name}\n"
    "Description: {description}"
)


class _ClassifyResult(BaseModel):
    is_destructive: bool = Field(description="True if the tool is destructive.")
    rationale: str = Field(default="", description="One short sentence of reasoning.")


def _description_hash(description: str) -> str:
    return hashlib.md5(description.encode(), usedforsecurity=False).hexdigest()  # nosec B324


async def is_tool_destructive(tool_name: str, description: str = "") -> bool:
    """Return whether ``tool_name`` must be gated by HIL. Fails closed."""
    if tool_name in HIL_EXEMPT_TOOLS:
        return False

    try:
        registry = await get_tool_registry()
        flag = registry.is_tool_destructive(tool_name)
        if flag is not None:
            return flag

        description_hash = _description_hash(description)
        record = await hil_tool_risk_collection.find_one(
            {"tool_name": tool_name, "description_hash": description_hash}
        )
        if record is not None:
            registry.mark_tool_destructive(tool_name, record["is_destructive"])
            return bool(record["is_destructive"])

        result = await ainvoke_structured(
            _ClassifyResult,
            _CLASSIFY_PROMPT.format(name=tool_name, description=description or "(none provided)"),
            label="hil_tool_classification",
        )
        classification = HILToolRiskRecord(
            tool_name=tool_name,
            description_hash=description_hash,
            is_destructive=result.is_destructive,
            rationale=result.rationale,
        )
        await hil_tool_risk_collection.update_one(
            {"tool_name": tool_name, "description_hash": description_hash},
            {"$set": classification.model_dump()},
            upsert=True,
        )
        registry.mark_tool_destructive(tool_name, result.is_destructive)
        return result.is_destructive
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Failed to classify '{tool_name}', failing closed (destructive): {e}"
        )
        return True
