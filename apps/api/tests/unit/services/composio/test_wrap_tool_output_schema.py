"""wrap_tool carries the provider's output schema into tool.metadata — the only feed for the Returns section of execute schema docs (schema_docs.py)."""

from typing import Any

import pytest

from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.execute.schema_docs import render_tool_doc
from app.agents.tools.execute.tool_info import tool_contract
from app.constants.execute import RETURNS_INLINE_MAX_CHARS
from app.services.composio.langchain_composio_service import LangchainProvider
from tests.factories import make_composio_tool

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "data": {"type": "object", "properties": {"messages": {"type": "array"}}},
        "successful": {"type": "boolean"},
        "error": {"type": "string"},
    },
}


def _noop_execute(_tool: str, _kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"successful": True, "data": {}, "error": None}


@pytest.mark.unit
class TestWrapToolOutputSchema:
    def test_output_parameters_land_on_tool_metadata(self) -> None:
        wrapped = LangchainProvider().wrap_tool(
            make_composio_tool(output_parameters=OUTPUT_SCHEMA), _noop_execute
        )
        assert wrapped.metadata == {"output_parameters": OUTPUT_SCHEMA}

    def test_a_shapeless_output_schema_sets_no_metadata(self) -> None:
        # The factory default has empty properties — a Returns section saying
        # "an object" documents nothing and must not render.
        wrapped = LangchainProvider().wrap_tool(make_composio_tool(), _noop_execute)
        assert wrapped.metadata is None

    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_the_discovery_doc_carries_the_returns(self) -> None:
        wrapped = LangchainProvider().wrap_tool(
            make_composio_tool(output_parameters=OUTPUT_SCHEMA), _noop_execute
        )
        info = await tool_contract(ResolvedTool(wrapped.name, wrapped, True))
        doc = render_tool_doc(info, RETURNS_INLINE_MAX_CHARS)
        assert "Returns: {data?:{messages?:any[]}, successful?:bool, error?:str}" in doc
