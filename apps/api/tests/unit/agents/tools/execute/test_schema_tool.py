"""get_tool_schema — the host-side depth behind the discovery pointer."""

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, patch

from langchain_core.tools import StructuredTool
import pytest

from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.execute.schema_docs import _args_schema_of
from app.agents.tools.execute.schema_tool import get_tool_schema
from app.agents.tools.execute.tool_info import ToolContract, full_tool_info
from app.db.repositories.tool_shapes import tool_shapes_repository
from app.models.tool_shape_models import ToolOutputShapeDocument

MODULE = "app.agents.tools.execute.schema_tool"
INFO = "app.agents.tools.execute.tool_info"
CONFIG = {"configurable": {"user_id": "u1"}}


def _info(**overrides: object) -> ToolContract:
    defaults: dict = {
        "tool_name": "GMAIL_FETCH_EMAILS",
        "description": "Fetch emails.",
        "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer"}}},
        "provider_output_schema": {
            "type": "object",
            "properties": {"data": {"type": "object"}},
            "required": ["data"],
        },
        "observed_output_schema": None,
        "observed_call_count": 0,
    }
    defaults.update(overrides)
    return ToolContract(**defaults)


@pytest.mark.unit
class TestGetToolSchema:
    async def test_returns_args_and_type_notation_never_raw_schema_json(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=_info())) as info:
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        info.assert_awaited_once_with("u1", "GMAIL_FETCH_EMAILS")
        assert "## GMAIL_FETCH_EMAILS" in doc
        assert "max_results?: int" in doc  # args are field lines
        assert "Returns: {data:obj}" in doc  # returns are type notation
        assert '"provider_output_schema"' not in doc  # never the raw dump

    async def test_observed_only_shape_carries_its_confidence(self) -> None:
        info = _info(
            provider_output_schema=None,
            observed_output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            observed_call_count=17,
        )
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=info)):
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        assert "Returns: {ok?:bool}" in doc
        assert "observed from 17 real calls" in doc

    async def test_undocumented_shape_says_so_instead_of_inventing_one(self) -> None:
        info = _info(provider_output_schema=None, observed_output_schema=None)
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=info)):
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        assert "not documented yet" in doc
        assert "Returns: {" not in doc

    async def test_unknown_tool_is_a_structured_error(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=None)):
            doc = await get_tool_schema.ainvoke({"tool_name": "NOPE"}, config=CONFIG)
        body = json.loads(doc)
        assert body["ok"] is False
        assert body["error"] == "unknown_tool"


@pytest.mark.unit
class TestGetToolSchemaLayout:
    async def test_a_documented_tool_reads_header_args_then_returns(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=_info())):
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        assert doc.split("\n") == [
            "## GMAIL_FETCH_EMAILS",
            "Fetch emails.",
            "Args, ? = optional:",
            "max_results?: int",
            "Returns: {data:obj}",
        ]

    async def test_an_undocumented_return_shape_tells_the_model_to_inspect_first(self) -> None:
        info = _info(provider_output_schema=None, observed_output_schema=None)
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=info)):
            doc = await get_tool_schema.ainvoke({"tool_name": "GMAIL_FETCH_EMAILS"}, config=CONFIG)
        assert doc.split("\n")[-1] == (
            "Return shape: not documented yet; it is learned from real calls. "
            "Inspect the first response before consuming fields."
        )

    async def test_an_unknown_tool_says_what_to_do_next(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=None)):
            doc = await get_tool_schema.ainvoke({"tool_name": "NOPE"}, config=CONFIG)
        assert json.loads(doc) == {
            "ok": False,
            "error": "unknown_tool",
            "next": "Use the exact tool name retrieve_tools returned.",
        }


def _catalog_tool(response_schema: dict[str, object] | None) -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda max_results: None,
        name="GMAIL_FETCH_EMAILS",
        description="  Fetch emails.  ",
        metadata={"output_parameters": response_schema} if response_schema else None,
    )


def _observed(schema: dict[str, object], calls: int) -> ToolOutputShapeDocument:
    return ToolOutputShapeDocument(
        tool_name="GMAIL_FETCH_EMAILS",
        output_schema=schema,
        call_count=calls,
        last_seen=datetime(2026, 1, 1, tzinfo=UTC),
    )


PROVIDER = {"type": "object", "properties": {"data": {"type": "object"}}, "required": ["data"]}
OBSERVED = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


@pytest.mark.unit
class TestFullToolInfo:
    async def test_an_unknown_name_has_no_contract(self) -> None:
        with patch(f"{INFO}.resolve_tool", new=AsyncMock(return_value=None)):
            assert await full_tool_info("u1", "NOPE") is None

    @pytest.mark.parametrize(
        ("provider", "observed", "compact"),
        [
            (PROVIDER, _observed(OBSERVED, 4), "{data:obj}"),
            (None, _observed(OBSERVED, 4), "{ok?:bool}"),
        ],
        ids=["provider_wins", "observed_fallback"],
    )
    async def test_the_contract_carries_both_shapes_and_the_effective_one(
        self,
        provider: dict[str, object] | None,
        observed: ToolOutputShapeDocument,
        compact: str,
    ) -> None:
        resolved = ResolvedTool(
            "GMAIL_FETCH_EMAILS", _catalog_tool(provider), True, shape_scope="mcp:gmail"
        )
        get_shape = AsyncMock(return_value=observed)
        with (
            patch(f"{INFO}.resolve_tool", new=AsyncMock(return_value=resolved)) as resolve,
            patch.object(tool_shapes_repository, "get_shape", new=get_shape),
        ):
            contract = await full_tool_info("u1", "GMAIL_FETCH_EMAILS")
        resolve.assert_awaited_once_with("u1", "GMAIL_FETCH_EMAILS")
        get_shape.assert_awaited_once_with("mcp:gmail", "GMAIL_FETCH_EMAILS")
        assert contract == ToolContract(
            tool_name="GMAIL_FETCH_EMAILS",
            description="Fetch emails.",
            input_schema=_args_schema_of(resolved.tool),
            provider_output_schema=provider,
            observed_output_schema=OBSERVED,
            observed_call_count=4,
            compact_output_type=compact,
        )

    @pytest.mark.parametrize(
        "unusable", [{}, "see the provider docs"], ids=["empty", "not_a_schema"]
    )
    async def test_an_unusable_provider_schema_is_no_provider_schema(
        self, unusable: object
    ) -> None:
        tool = StructuredTool.from_function(
            func=lambda max_results: None,
            name="GMAIL_FETCH_EMAILS",
            description="Fetch emails.",
            metadata={"output_parameters": unusable},
        )
        resolved = ResolvedTool("GMAIL_FETCH_EMAILS", tool, True)
        with (
            patch(f"{INFO}.resolve_tool", new=AsyncMock(return_value=resolved)),
            patch.object(tool_shapes_repository, "get_shape", new=AsyncMock(return_value=None)),
        ):
            contract = await full_tool_info("u1", "GMAIL_FETCH_EMAILS")
        assert contract is not None
        assert contract.provider_output_schema is None
        assert contract.compact_output_type is None

    async def test_a_never_observed_undocumented_tool_has_no_return_shape(self) -> None:
        resolved = ResolvedTool("GMAIL_FETCH_EMAILS", _catalog_tool(None), True)
        with (
            patch(f"{INFO}.resolve_tool", new=AsyncMock(return_value=resolved)),
            patch.object(tool_shapes_repository, "get_shape", new=AsyncMock(return_value=None)),
        ):
            contract = await full_tool_info("u1", "GMAIL_FETCH_EMAILS")
        assert contract is not None
        assert contract.observed_output_schema is None
        assert contract.observed_call_count == 0
        assert contract.compact_output_type is None
