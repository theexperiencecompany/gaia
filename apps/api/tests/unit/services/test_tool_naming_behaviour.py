"""Behaviour tests for per-user GAIA MCP tool naming."""

from langchain_core.tools import BaseTool, StructuredTool
import pytest

from app.constants.mcp import MCP_RENAMED_TOOL_NOTE
from app.models.integration_models import StoredIntegrationTool
from app.services.mcp import tool_naming
from app.services.mcp.tool_naming import ServerToolNames


def _stamped_tool(name: str, description: str = "does a thing") -> BaseTool:
    async def _run() -> str:
        return "ok"

    tool = StructuredTool.from_function(coroutine=_run, name=name, description=description)
    tool_naming.stamp_tool_metadata([tool], "int-1", "https://mcp.example", "Acme Docs")
    return tool


@pytest.mark.unit
class TestMasterRename:
    def test_returns_original_name_and_note_end(self) -> None:
        note = MCP_RENAMED_TOOL_NOTE.format(original="search", renamed="acme_search")
        tool = StoredIntegrationTool(name="acme_search", description=note + "Find pages.")

        rename = tool_naming.master_rename(tool)

        assert rename == tool_naming.MasterRename(original="search", note_end=len(note))
        assert (note + "Find pages.")[rename.note_end :] == "Find pages."

    def test_none_when_entry_holds_server_name(self) -> None:
        note = MCP_RENAMED_TOOL_NOTE.format(original="search", renamed="acme_search")
        tool = StoredIntegrationTool(name="search", description=note + "Find pages.")

        assert tool_naming.master_rename(tool) is None

    def test_none_without_description(self) -> None:
        assert tool_naming.master_rename(StoredIntegrationTool(name="search")) is None

    def test_none_for_plain_description(self) -> None:
        tool = StoredIntegrationTool(name="search", description="Find pages.")

        assert tool_naming.master_rename(tool) is None


@pytest.mark.unit
class TestApplyGaiaNames:
    def test_keeps_going_after_an_unrenamed_tool(self) -> None:
        keep = _stamped_tool("keep", "keep docs")
        rename = _stamped_tool("search", "search docs")

        renamed = tool_naming.apply_gaia_names(
            [keep, rename], {"keep": "keep", "search": "acme_docs_search"}
        )

        assert renamed == {"search": "acme_docs_search"}
        assert keep.name == "keep"
        assert keep.description == "keep docs"
        assert rename.name == "acme_docs_search"
        assert rename.description == (
            MCP_RENAMED_TOOL_NOTE.format(original="search", renamed="acme_docs_search")
            + "search docs"
        )


@pytest.mark.unit
class TestIndexToolNames:
    def test_reserved_name_is_prefixed_with_source_name(self) -> None:
        server = ServerToolNames("Acme Docs", ["search", "fetch"])

        names = tool_naming.index_tool_names(server, {"search"})

        assert names == {"search": "acme_docs_search", "fetch": "fetch"}


@pytest.mark.unit
class TestSharedIndexTools:
    def test_returns_every_tool_under_its_index_name(self) -> None:
        keep = _stamped_tool("fetch", "fetch docs")
        clash = _stamped_tool("search", "search docs")
        last = _stamped_tool("list", "list docs")
        server = ServerToolNames("Acme Docs", ["fetch", "search", "list"])

        result = tool_naming.shared_index_tools([keep, clash, last], server, {"search"})

        assert [t.name for t in result] == ["fetch", "acme_docs_search", "list"]
        assert result[0] is keep
        assert result[2] is last
        assert result[1] is not clash
        assert result[1].description.startswith("Note: this tool is called search")
        assert clash.name == "search"
        assert clash.description == "search docs"
