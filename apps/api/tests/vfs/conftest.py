"""
Pytest fixtures for VFS (Virtual Filesystem) tests.

Provides shared fixtures for mocking MongoDB, VFS, LLM, and other dependencies.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_vfs_collection():
    """Create a mock VFS nodes collection for MongoDB tests."""
    mock = AsyncMock()
    mock.find_one = AsyncMock(return_value=None)
    mock.update_one = AsyncMock()
    mock.insert_one = AsyncMock()
    mock.delete_one = AsyncMock()
    mock.delete_many = AsyncMock()
    mock.find = MagicMock()
    return mock


@pytest.fixture
def mock_vfs_service():
    """Create a mock VFS service for tool tests."""
    from app.models.vfs_models import (
        VFSListResponse,
        VFSNodeResponse,
        VFSNodeType,
        VFSSearchResult,
        VFSSessionInfo,
    )

    mock = AsyncMock()
    mock.write = AsyncMock(return_value="/users/user123/global/executor/files/test.txt")
    mock.read = AsyncMock(return_value="file content")
    mock.exists = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    mock.mkdir = AsyncMock(return_value="/users/user123/global/executor/files/newdir")
    mock.move = AsyncMock(return_value="/users/user123/global/new.txt")
    mock.copy = AsyncMock(return_value="/users/user123/global/copy.txt")
    mock.append = AsyncMock(return_value="/users/user123/global/log.txt")

    mock.list_dir = AsyncMock(
        return_value=VFSListResponse(
            path="/users/user123/global/executor/files",
            items=[
                VFSNodeResponse(
                    path="/users/user123/global/executor/files/file1.txt",
                    name="file1.txt",
                    node_type=VFSNodeType.FILE,
                    size_bytes=100,
                ),
            ],
            total_count=1,
        )
    )

    mock.info = AsyncMock(
        return_value=VFSNodeResponse(
            path="/users/user123/global/test.txt",
            name="test.txt",
            node_type=VFSNodeType.FILE,
            size_bytes=100,
        )
    )

    mock.search = AsyncMock(
        return_value=VFSSearchResult(
            matches=[
                VFSNodeResponse(
                    path="/users/user123/global/data.json",
                    name="data.json",
                    node_type=VFSNodeType.FILE,
                    size_bytes=50,
                )
            ],
            total_count=1,
            pattern="*.json",
            base_path="/users/user123/global",
        )
    )

    mock.tree = AsyncMock(
        return_value=MagicMock(
            name="executor",
            path="/users/user123/global/executor",
            node_type=MagicMock(value="folder"),
            children=[
                MagicMock(
                    name="files",
                    path="/users/user123/global/executor/files",
                    node_type=MagicMock(value="folder"),
                    size_bytes=0,
                    children=[],
                )
            ],
        )
    )

    mock.get_session_info = AsyncMock(
        return_value=VFSSessionInfo(
            conversation_id="conv1",
            path="/users/user123/global/executor/sessions/conv1",
            agents=["gmail", "github"],
            file_count=5,
            total_size_bytes=5000,
        )
    )

    return mock


@pytest.fixture
def mock_llm():
    """Create a mock LLM for context tracking tests."""
    mock = MagicMock()
    mock.get_num_tokens_from_messages = MagicMock(
        side_effect=lambda msgs: sum(len(str(m.content)) // 4 + 4 for m in msgs)
    )
    mock.get_num_tokens = MagicMock(side_effect=lambda s: len(s) // 4)
    return mock


@pytest.fixture
def mock_runnable_config():
    """Create a mock RunnableConfig with standard user context."""
    return {
        "metadata": {
            "user_id": "user123",
            "conversation_id": "conv1",
            "agent_name": "executor",
        },
        "configurable": {
            "user_id": "user123",
            "thread_id": "conv1",
            "agent_name": "executor",
            "provider": "openai",
            "max_tokens": 128000,
        },
    }


@pytest.fixture
def mock_store():
    """Create a mock LangGraph store."""
    return MagicMock()
