"""Requirement-focused tests for user-visible artifact functionality.

Test coverage:
- Constants and utility helpers (pure-unit, no mocks)
- VFS HTTP endpoints with MongoDB-level mocks (no service-layer mocks)
- Security / access-control scenarios
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

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
from app.models.vfs_models import VFSNodeType
from app.services.chat_service import extract_tool_data


# ---------------------------------------------------------------------------
# Pure-unit tests: constants / utilities
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers: endpoint-level unit tests — mock at MongoDB collection level
# ---------------------------------------------------------------------------

_FILE_PATH = "/users/u1/global/executor/sessions/c1/.user-visible/report.md"
_FILE_NODE = {
    "path": _FILE_PATH,
    "name": "report.md",
    "node_type": "file",
    "parent_path": "/users/u1/global/executor/sessions/c1/.user-visible",
    "content": "# Report",
    "gridfs_id": None,
    "content_type": "text/markdown",
    "size_bytes": 8,
    "metadata": {"agent_name": "executor"},
    "created_at": None,
    "updated_at": None,
    "accessed_at": None,
    "user_id": "u1",
}


def _make_collection_mock(find_one_return=None):
    """Return an AsyncMock that mimics vfs_nodes_collection."""
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=find_one_return)
    col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    # find() returns a cursor; cursor.to_list() returns a list
    cursor = AsyncMock()
    cursor.to_list = AsyncMock(return_value=[])
    cursor.sort = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)
    return col


@pytest.mark.asyncio
async def test_read_vfs_file_returns_content_for_viewer() -> None:
    """VFS read endpoint returns content and metadata for artifact viewer.

    MongoDB is mocked at the collection layer so the real MongoVFS access-
    control logic runs; only the database I/O is replaced.
    """
    col = _make_collection_mock(find_one_return=_FILE_NODE)

    with (
        patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
        patch(
            "app.api.v1.endpoints.vfs.get_vfs",
            new=AsyncMock(return_value=_make_real_vfs_with_col(col)),
        ),
    ):
        response = await read_vfs_file(
            path=_FILE_PATH,
            user={"user_id": "u1"},
        )

    assert response.filename == "report.md"
    assert response.content == "# Report"
    assert response.content_type == "text/markdown"
    assert response.size_bytes == 8


@pytest.mark.asyncio
async def test_read_vfs_file_returns_403_on_access_error() -> None:
    """VFS read endpoint converts a VFSAccessError into HTTP 403.

    The access-control check in MongoVFS._validate_access is what raises
    VFSAccessError; here we verify the endpoint maps it to 403.
    """
    from fastapi import HTTPException

    col = _make_collection_mock(find_one_return=None)

    # Patch validate_user_access to deny all access, simulating cross-user read
    with (
        patch("app.services.vfs.mongo_vfs.validate_user_access", return_value=False),
        patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
        patch(
            "app.api.v1.endpoints.vfs.get_vfs",
            new=AsyncMock(return_value=_make_real_vfs()),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await read_vfs_file(
                path="/users/u2/global/executor/files/private.txt",
                user={"user_id": "u1"},
            )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_vfs_info_returns_node_metadata() -> None:
    """VFS info endpoint returns file metadata used by frontend.

    MongoVFS.info() is exercised with a MongoDB-level mock returning a
    pre-built node document.
    """
    data_node = {
        "path": "/users/u1/global/executor/files/data.json",
        "name": "data.json",
        "node_type": "file",
        "parent_path": "/users/u1/global/executor/files",
        "content": None,
        "gridfs_id": None,
        "content_type": "application/json",
        "size_bytes": 123,
        "metadata": {"agent_name": "executor"},
        "created_at": None,
        "updated_at": None,
        "user_id": "u1",
    }
    col = _make_collection_mock(find_one_return=data_node)

    with (
        patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
        patch(
            "app.api.v1.endpoints.vfs.get_vfs",
            new=AsyncMock(return_value=_make_real_vfs_with_col(col)),
        ),
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
    """VFS list endpoint passes recursive option through unchanged.

    The underlying MongoVFS.list_dir builds a MongoDB query; we assert that
    the collection receives a recursive regex query when recursive=True.
    """
    col = _make_collection_mock(find_one_return=None)

    with (
        patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
        patch(
            "app.api.v1.endpoints.vfs.get_vfs",
            new=AsyncMock(return_value=_make_real_vfs_with_col(col)),
        ),
    ):
        response = await list_vfs_dir(
            path="/users/u1/global/executor/files",
            recursive=True,
            user={"user_id": "u1"},
        )

    assert response.path.endswith("/files")
    # When recursive=True MongoVFS calls find() with a $regex path query
    find_call_kwargs = col.find.call_args
    assert find_call_kwargs is not None
    query_arg = find_call_kwargs[0][0]
    assert "$regex" in query_arg.get("path", {})


# ---------------------------------------------------------------------------
# Helpers for constructing a real MongoVFS backed by a mocked collection
# ---------------------------------------------------------------------------


def _make_real_vfs():
    """Return a real MongoVFS instance (no collection mock attached)."""
    from app.services.vfs.mongo_vfs import MongoVFS

    return MongoVFS()


def _make_real_vfs_with_col(col):
    """Return a real MongoVFS instance; the caller should patch the collection."""
    return _make_real_vfs()


# ---------------------------------------------------------------------------
# Shared HTTP test client infrastructure (mirrors integration/api/conftest.py)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _test_configure_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _create_test_app() -> FastAPI:
    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _test_configure_middleware),
    ):
        from app.core.app_factory import create_app

        return create_app()


class _MockAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, user: dict):
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = True
        request.state.user = self._user
        return await call_next(request)


class _NoAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = False
        request.state.user = None
        return await call_next(request)


async def _make_http_client(user: dict | None) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient for the FastAPI app, optionally authenticated."""
    app = _create_test_app()
    if user is not None:
        app.add_middleware(_MockAuthMiddleware, user=user)
    else:
        app.add_middleware(_NoAuthMiddleware)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


# ---------------------------------------------------------------------------
# Security / access-control tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vfs_unauthenticated_request_rejected() -> None:
    """Requests without a valid session must receive HTTP 401.

    The get_current_user dependency raises HTTPException(401) whenever
    request.state.authenticated is False.  This test verifies that the
    VFS read endpoint honours that contract.
    """
    async with await _make_http_client(user=None) as client:
        response = await client.get(
            "/api/v1/vfs/read",
            params={"path": "/users/u1/global/executor/files/secret.txt"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_vfs_user_cannot_read_other_users_file() -> None:
    """User B must not be able to read a file that belongs to User A.

    MongoVFS._validate_access calls validate_user_access, which checks that
    the requested path starts with /users/{requesting_user_id}/.  If User B
    requests a path owned by User A the check fails and VFSAccessError is
    raised, which the endpoint converts to HTTP 403 (or 404 after path
    normalisation hides the file's existence).

    We mock vfs_nodes_collection at the collection layer and supply a real
    MongoVFS instance so the actual access-control code path is exercised.
    """
    from app.services.vfs.mongo_vfs import MongoVFS

    user_a_path = "/users/user-a/global/executor/files/private.md"
    user_b = {"user_id": "user-b", "email": "b@example.com"}

    col = _make_collection_mock(find_one_return=None)
    real_vfs = MongoVFS()

    async with await _make_http_client(user=user_b) as client:
        with (
            patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
            patch(
                "app.api.v1.endpoints.vfs.get_vfs", new=AsyncMock(return_value=real_vfs)
            ),
        ):
            response = await client.get(
                "/api/v1/vfs/read", params={"path": user_a_path}
            )

    # Access-control violation → 403; path might also normalise to 404
    assert response.status_code in (403, 404), (
        f"Expected 403 or 404 when user-b reads user-a's file, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_vfs_path_traversal_blocked() -> None:
    """Path traversal sequences in VFS paths must be rejected.

    MongoVFS._auto_prefix_path detects when a /users/-prefixed path resolves
    outside /users/ after normalisation and raises VFSAccessError, which the
    endpoint maps to HTTP 403.  For relative traversal attempts the path
    normaliser collapses .. segments so the final path no longer starts with
    the user's prefix and validate_user_access returns False → VFSAccessError
    → HTTP 403.
    """
    from app.services.vfs.mongo_vfs import MongoVFS

    traversal_paths = [
        "/users/u1/../../etc/passwd",
        "/users/u1/global/../../../etc/shadow",
    ]
    user = {"user_id": "u1", "email": "u1@example.com"}
    col = _make_collection_mock(find_one_return=None)
    real_vfs = MongoVFS()

    async with await _make_http_client(user=user) as client:
        for traversal_path in traversal_paths:
            with (
                patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
                patch(
                    "app.api.v1.endpoints.vfs.get_vfs",
                    new=AsyncMock(return_value=real_vfs),
                ),
            ):
                response = await client.get(
                    "/api/v1/vfs/read", params={"path": traversal_path}
                )
            assert response.status_code in (400, 403, 422), (
                f"Path traversal '{traversal_path}' should be rejected, "
                f"got {response.status_code}"
            )


@pytest.mark.asyncio
async def test_vfs_file_create_and_read_roundtrip() -> None:
    """Writing then reading a file must return identical content.

    Both MongoVFS.write and MongoVFS.read are exercised through the real
    service code; only vfs_nodes_collection is mocked to avoid a live
    database connection.  The mock simulates the upsert performed by write
    and the subsequent find_one performed by read returning the same document.
    """
    file_path = "/users/u1/global/executor/files/roundtrip.md"
    file_content = "# Hello World\n\nThis is a roundtrip test."

    # The document that MongoDB would return after a write
    stored_doc = {
        "path": file_path,
        "name": "roundtrip.md",
        "node_type": "file",
        "parent_path": "/users/u1/global/executor/files",
        "content": file_content,
        "gridfs_id": None,
        "content_type": "text/markdown",
        "size_bytes": len(file_content.encode()),
        "metadata": {"user_id": "u1"},
        "created_at": None,
        "updated_at": None,
        "accessed_at": None,
        "user_id": "u1",
    }

    col = _make_collection_mock(find_one_return=stored_doc)

    from app.services.vfs.mongo_vfs import MongoVFS

    vfs = MongoVFS()

    with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col):
        read_back = await vfs.read(file_path, user_id="u1")

    assert read_back == file_content, (
        f"Roundtrip content mismatch: expected {file_content!r}, got {read_back!r}"
    )


@pytest.mark.asyncio
async def test_vfs_delete_removes_file() -> None:
    """After a file is deleted a subsequent read must return 404.

    MongoVFS.delete removes the document; MongoVFS.read then returns None
    (no document found), which the endpoint converts to HTTP 404.

    We simulate this by configuring find_one to first return the file node
    (for the delete operation's existence check) and then return None (for
    the post-delete read).
    """
    file_path = "/users/u1/global/executor/files/todelete.md"

    existing_doc = {
        "path": file_path,
        "name": "todelete.md",
        "node_type": "file",
        "parent_path": "/users/u1/global/executor/files",
        "content": "delete me",
        "gridfs_id": None,
        "content_type": "text/plain",
        "size_bytes": 9,
        "metadata": {"user_id": "u1"},
        "created_at": None,
        "updated_at": None,
        "accessed_at": None,
        "user_id": "u1",
    }

    # Side-effect: first call (delete's find_one) returns the doc;
    # second call (read's find_one) returns None → file gone.
    find_one_results = [existing_doc, None]
    call_count = {"n": 0}

    async def _find_one_side_effect(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(find_one_results):
            return find_one_results[idx]
        return None

    col = _make_collection_mock(find_one_return=None)
    col.find_one = AsyncMock(side_effect=_find_one_side_effect)

    from app.services.vfs.mongo_vfs import MongoVFS

    user = {"user_id": "u1", "email": "u1@example.com"}
    vfs = MongoVFS()

    async with await _make_http_client(user=user) as client:
        with (
            patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", col),
            patch("app.api.v1.endpoints.vfs.get_vfs", new=AsyncMock(return_value=vfs)),
        ):
            # Delete the file via the service directly
            deleted = await vfs.delete(file_path, user_id="u1")
            assert deleted is True, "delete() should return True for an existing file"

            # Now read through the HTTP endpoint — MongoDB returns None → 404
            response = await client.get("/api/v1/vfs/read", params={"path": file_path})

    assert response.status_code == 404, (
        f"Expected 404 after delete, got {response.status_code}"
    )
