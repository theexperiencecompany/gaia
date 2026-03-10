"""Requirement-focused tests for user-visible artifact functionality."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.agents.tools.vfs_constants import (
    USER_VISIBLE_FOLDER,
    detect_artifact_content_type,
    is_user_visible_path,
)
from app.api.v1.endpoints.vfs import (
    get_vfs_info,
    list_vfs_dir,
    read_vfs_file,
    router,
)
from app.models.chat_models import tool_fields
from app.models.vfs_models import VFSListResponse, VFSNodeResponse, VFSNodeType
from app.services.chat_service import extract_tool_data
from app.services.vfs import VFSAccessError


def test_artifact_data_is_registered_for_stream_extraction() -> None:
    """artifact_data must be recognized by stream extraction pipeline."""
    assert "artifact_data" in tool_fields


def test_user_visible_folder_constant_matches_requirement() -> None:
    """The visibility folder is the dot-prefixed .user-visible folder."""
    assert USER_VISIBLE_FOLDER == ".user-visible"


def test_detect_artifact_content_type_prefers_markdown_and_html() -> None:
    """Common artifact formats should map to rich preview content types."""
    assert detect_artifact_content_type("md") == "text/markdown"
    assert detect_artifact_content_type("html") == "text/html"


def test_detect_artifact_content_type_defaults_to_text_plain() -> None:
    """Unknown extensions should still be renderable as plain text."""
    assert detect_artifact_content_type("unknownext") == "text/plain"


def test_is_user_visible_path_detects_only_session_visible_files() -> None:
    """Only paths under /.user-visible/ should be treated as visible artifacts."""
    assert is_user_visible_path(
        "/users/u1/global/executor/sessions/conv1/.user-visible/report.md"
    )
    assert not is_user_visible_path("/users/u1/global/executor/files/report.md")


def test_vfs_http_routes_exist_for_file_viewer() -> None:
    """Frontend file viewer requirements need read/info/list VFS endpoints."""
    routes = {getattr(route, "path", "") for route in router.routes}
    assert "/read" in routes
    assert "/info" in routes
    assert "/list" in routes


def test_extract_tool_data_maps_artifact_data_into_tool_data_array() -> None:
    """artifact_data events should normalize into ToolDataEntry shape."""
    payload = {
        "artifact_data": {
            "path": "/users/u1/global/executor/sessions/conv1/.user-visible/report.md",
            "filename": "report.md",
            "content_type": "text/markdown",
            "size_bytes": 123,
        }
    }

    result = extract_tool_data(json.dumps(payload))

    assert "tool_data" in result
    assert len(result["tool_data"]) == 1
    assert result["tool_data"][0]["tool_name"] == "artifact_data"


@pytest.mark.asyncio
async def test_read_vfs_file_returns_content_for_viewer() -> None:
    """VFS read endpoint returns content and metadata for artifact viewer."""
    mock_vfs = AsyncMock()
    mock_vfs.read = AsyncMock(return_value="# Report")
    mock_vfs.info = AsyncMock(
        return_value=SimpleNamespace(content_type="text/markdown", size_bytes=8)
    )

    with patch(
        "app.api.v1.endpoints.vfs.get_vfs", new=AsyncMock(return_value=mock_vfs)
    ):
        response = await read_vfs_file(
            path="/users/u1/global/executor/sessions/c1/.user-visible/report.md",
            user={"user_id": "u1"},
        )

    assert response.filename == "report.md"
    assert response.content == "# Report"
    assert response.content_type == "text/markdown"
    assert response.size_bytes == 8


@pytest.mark.asyncio
async def test_read_vfs_file_returns_403_on_access_error() -> None:
    """VFS read endpoint should convert access errors into HTTP 403."""
    mock_vfs = AsyncMock()
    mock_vfs.read = AsyncMock(
        side_effect=VFSAccessError(
            "/users/u2/global/executor/files/private.txt",
            "u1",
            "permission denied",
        )
    )

    with patch(
        "app.api.v1.endpoints.vfs.get_vfs", new=AsyncMock(return_value=mock_vfs)
    ):
        with pytest.raises(HTTPException) as exc_info:
            await read_vfs_file(
                path="/users/u1/global/executor/files/private.txt",
                user={"user_id": "u1"},
            )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_vfs_info_returns_node_metadata() -> None:
    """VFS info endpoint returns file metadata used by frontend."""
    mock_vfs = AsyncMock()
    node = VFSNodeResponse(
        path="/users/u1/global/executor/files/data.json",
        name="data.json",
        node_type=VFSNodeType.FILE,
        size_bytes=123,
        content_type="application/json",
        metadata={"agent_name": "executor"},
    )
    mock_vfs.info = AsyncMock(return_value=node)

    with patch(
        "app.api.v1.endpoints.vfs.get_vfs", new=AsyncMock(return_value=mock_vfs)
    ):
        response = await get_vfs_info(
            path="/users/u1/global/executor/files/data.json",
            user={"user_id": "u1"},
        )

    assert response.path.endswith("/files/data.json")
    assert response.node_type == VFSNodeType.FILE
    assert response.size_bytes == 123


@pytest.mark.asyncio
async def test_list_vfs_dir_honors_recursive_flag() -> None:
    """VFS list endpoint should pass recursive option through unchanged."""
    mock_vfs = AsyncMock()
    listing = VFSListResponse(
        path="/users/u1/global/executor/files", items=[], total_count=0
    )
    mock_vfs.list_dir = AsyncMock(return_value=listing)

    with patch(
        "app.api.v1.endpoints.vfs.get_vfs", new=AsyncMock(return_value=mock_vfs)
    ):
        response = await list_vfs_dir(
            path="/users/u1/global/executor/files",
            recursive=True,
            user={"user_id": "u1"},
        )

    assert response.path.endswith("/files")
    mock_vfs.list_dir.assert_awaited_once_with(
        "/users/u1/global/executor/files",
        user_id="u1",
        recursive=True,
    )
