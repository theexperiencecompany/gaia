"""Per-user GAIA names for MCP tools, derived from each tool's stamped server-side identity."""

import re
from typing import NamedTuple

from langchain_core.tools import BaseTool

from app.agents.tools.core.registry import get_tool_registry
from app.constants.execute import TICKET_NAMES
from app.constants.mcp import (
    MCP_INTEGRATION_ID_METADATA_KEY,
    MCP_RENAMED_TOOL_NOTE,
    MCP_SERVER_NAME_METADATA_KEY,
)
from app.models.integration_models import StoredIntegrationTool
from app.utils.mcp_utils import gaia_tool_names

# A live tool's server-side identity, stamped before any GAIA-side rename so a
# later collision recompute can always derive the name from the original.
_SERVER_DESCRIPTION_KEY = "mcp_server_description"
_SOURCE_NAME_KEY = "mcp_source_name"


# The note master led a renamed tool's stored description with, built from MCP_RENAMED_TOOL_NOTE.
_MASTER_RENAME_NOTE = re.compile(
    re.escape(MCP_RENAMED_TOOL_NOTE)
    .replace(re.escape("{original}"), r"(?P<original>\S+)", 1)
    .replace(re.escape("{original}"), r"(?P=original)")
    .replace(re.escape("{renamed}"), r"(?P<renamed>\S+)", 1)
    .replace(re.escape("{renamed}"), r"(?P=renamed)"),
    re.DOTALL,
)


class ServerToolNames(NamedTuple):
    """One connected MCP integration's display name and its tools' server-side names."""

    source_name: str
    server_names: list[str]


class MasterRename(NamedTuple):
    """A stored entry master renamed: the server's own name, and where the note ends in the description."""

    original: str
    note_end: int


def master_rename(tool: StoredIntegrationTool) -> MasterRename | None:
    """Return the rename master stored for this entry, or None for an entry holding the server's own name."""
    if tool.description is None:
        return None
    match = _MASTER_RENAME_NOTE.match(tool.description)
    if match is None or match.group("renamed") != tool.name:
        return None
    return MasterRename(original=match.group("original"), note_end=match.end())


async def reserved_tool_names() -> set[str]:
    registry = await get_tool_registry()
    return {*registry.get_tool_names(), *TICKET_NAMES}


def server_identity(tool: BaseTool) -> tuple[str, str]:
    metadata = tool.metadata or {}
    return str(metadata[MCP_SERVER_NAME_METADATA_KEY]), str(metadata[_SERVER_DESCRIPTION_KEY])


def live_server_tool_names(tools: list[BaseTool]) -> ServerToolNames:
    """Read one connected integration's server-side names back from its stamped live tools."""
    return ServerToolNames(
        source_name=str((tools[0].metadata or {})[_SOURCE_NAME_KEY]),
        server_names=[server_identity(tool)[0] for tool in tools],
    )


def apply_gaia_names(tools: list[BaseTool], names: dict[str, str]) -> dict[str, str]:
    """Rename tools from their server identity per names; return server name -> new name for the prefixed ones."""
    renamed: dict[str, str] = {}
    for tool in tools:
        server_name, server_description = server_identity(tool)
        tool.name = names[server_name]
        if tool.name == server_name:
            tool.description = server_description
            continue
        tool.description = (
            MCP_RENAMED_TOOL_NOTE.format(original=server_name, renamed=tool.name)
            + server_description
        )
        renamed[server_name] = tool.name
    return renamed


def gaia_names_by_integration(
    server_tools: dict[str, ServerToolNames], reserved: set[str]
) -> dict[str, dict[str, str]]:
    """Per integration, server name -> GAIA name, unique across integrations.

    A name another integration also exposes is prefixed on both. Integrations are
    named in id order, so two sources sharing a prefix split it the same way whatever connected first.
    """
    exposed = {name for own in server_tools.values() for name in own.server_names}
    assigned: set[str] = set()
    names: dict[str, dict[str, str]] = {}
    for integration_id in sorted(server_tools):
        own = server_tools[integration_id]
        shared = {
            name
            for other_id, other in server_tools.items()
            if other_id != integration_id
            for name in other.server_names
        }
        names[integration_id] = gaia_tool_names(
            own.source_name, own.server_names, reserved, shared, taken=exposed | assigned
        )
        assigned.update(names[integration_id].values())
    return names


def index_tool_names(server: ServerToolNames, reserved: set[str]) -> dict[str, str]:
    """Server name -> the name Chroma indexes the tool under: shared by every user, so renamed only for GAIA's reserved names."""
    return gaia_tool_names(server.source_name, server.server_names, reserved, shared=())


def live_names_by_index_key(tools: list[BaseTool], reserved: set[str]) -> dict[str, str]:
    """Map one integration's Chroma keys to this user's live names, which a collision may have prefixed."""
    index_names = index_tool_names(live_server_tool_names(tools), reserved)
    return {index_names[server_identity(tool)[0]]: tool.name for tool in tools}


def shared_index_tools(
    tools: list[BaseTool], server: ServerToolNames, reserved: set[str]
) -> list[BaseTool]:
    """Return the tools as Chroma sees them, named per index_tool_names."""
    index_names = index_tool_names(server, reserved)
    index_tools: list[BaseTool] = []
    for tool in tools:
        if tool.name == index_names[server_identity(tool)[0]]:
            index_tools.append(tool)
            continue
        index_tool = tool.model_copy()
        apply_gaia_names([index_tool], index_names)
        index_tools.append(index_tool)
    return index_tools


def stamp_tool_metadata(
    raw_tools: list[BaseTool],
    integration_id: str,
    server_url: str,
    source_name: str,
) -> None:
    """Attach provenance metadata to every converted tool, before any rename.

    server_url goes to tools with mcp_ui metadata; integration_id and the
    server identity are stamped onto all of them so consumers resolve
    tool -> integration without the global ToolRegistry.
    """
    for raw_tool in raw_tools:
        if raw_tool.metadata and "mcp_ui" in raw_tool.metadata:
            raw_tool.metadata["mcp_server_url"] = server_url

    for raw_tool in raw_tools:
        if raw_tool.metadata is None:
            raw_tool.metadata = {}
        raw_tool.metadata[MCP_INTEGRATION_ID_METADATA_KEY] = integration_id
        raw_tool.metadata[MCP_SERVER_NAME_METADATA_KEY] = raw_tool.name
        raw_tool.metadata[_SERVER_DESCRIPTION_KEY] = raw_tool.description
        raw_tool.metadata[_SOURCE_NAME_KEY] = source_name
