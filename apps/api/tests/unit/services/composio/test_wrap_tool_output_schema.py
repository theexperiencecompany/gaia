"""wrap_tool carries the provider's output schema into tool.metadata — the only
feed for the Returns section of execute schema docs (schema_docs.py)."""

from typing import Any

import pytest

from app.agents.tools.execute.schema_docs import render_tool_doc
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

    def test_the_wrapped_tool_renders_a_returns_section(self) -> None:
        wrapped = LangchainProvider().wrap_tool(
            make_composio_tool(output_parameters=OUTPUT_SCHEMA), _noop_execute
        )
        doc = render_tool_doc(wrapped)
        assert "Returns:" in doc
        assert '"messages"' in doc
