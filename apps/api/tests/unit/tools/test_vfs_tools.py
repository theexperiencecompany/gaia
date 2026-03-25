"""Tests for app/agents/tools/vfs_tools.py and app/agents/tools/file_tools.py."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _get_context
# ---------------------------------------------------------------------------

USER_ID = "user123"
THREAD_ID = "thread-abc"
VFS_SESSION = "session-xyz"
AGENT_NAME = "research_agent"


def _make_config(
    configurable: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    if configurable is not None:
        cfg["configurable"] = configurable
    if metadata is not None:
        cfg["metadata"] = metadata
    return cfg


class TestGetContext:
    """Tests for the _get_context helper."""

    def _import(self):
        from app.agents.tools.vfs_tools import _get_context

        return _get_context

    def test_shared_session_mode_with_subagent_id(self):
        _get_context = self._import()
        config = _make_config(
            configurable={
                "user_id": USER_ID,
                "vfs_session_id": VFS_SESSION,
                "thread_id": THREAD_ID,
                "subagent_id": "sub-1",
            },
            metadata={"agent_name": AGENT_NAME},
        )
        ctx = _get_context(config)
        assert ctx["user_id"] == USER_ID
        assert ctx["conversation_id"] == VFS_SESSION
        assert ctx["agent_name"] == "executor"
        assert ctx["written_by"] == "sub-1"
        assert ctx["agent_thread_id"] == THREAD_ID
        assert ctx["vfs_session_id"] == VFS_SESSION

    def test_shared_session_mode_falls_back_to_agent_name(self):
        _get_context = self._import()
        config = _make_config(
            configurable={
                "user_id": USER_ID,
                "vfs_session_id": VFS_SESSION,
                "thread_id": THREAD_ID,
            },
            metadata={"agent_name": AGENT_NAME},
        )
        ctx = _get_context(config)
        assert ctx["written_by"] == AGENT_NAME

    def test_shared_session_mode_raises_without_writer(self):
        _get_context = self._import()
        config = _make_config(
            configurable={
                "user_id": USER_ID,
                "vfs_session_id": VFS_SESSION,
                "thread_id": THREAD_ID,
            },
            metadata={},
        )
        with pytest.raises(ValueError, match="requires 'subagent_id'"):
            _get_context(config)

    def test_fallback_mode_with_thread_id(self):
        _get_context = self._import()
        config = _make_config(
            configurable={
                "user_id": USER_ID,
                "thread_id": THREAD_ID,
            },
            metadata={"agent_name": AGENT_NAME},
        )
        ctx = _get_context(config)
        assert ctx["conversation_id"] == THREAD_ID
        assert ctx["agent_name"] == AGENT_NAME
        assert ctx["written_by"] == AGENT_NAME
        assert ctx["vfs_session_id"] is None

    def test_fallback_mode_raises_without_thread_id(self):
        _get_context = self._import()
        config = _make_config(
            configurable={"user_id": USER_ID},
            metadata={"agent_name": AGENT_NAME},
        )
        with pytest.raises(ValueError, match="requires either 'vfs_session_id'"):
            _get_context(config)

    def test_fallback_mode_raises_without_writer(self):
        _get_context = self._import()
        config = _make_config(
            configurable={"user_id": USER_ID, "thread_id": THREAD_ID},
            metadata={},
        )
        with pytest.raises(ValueError, match="requires 'subagent_id'"):
            _get_context(config)

    def test_user_id_from_metadata_fallback(self):
        _get_context = self._import()
        config = _make_config(
            configurable={"thread_id": THREAD_ID},
            metadata={"user_id": USER_ID, "agent_name": AGENT_NAME},
        )
        ctx = _get_context(config)
        assert ctx["user_id"] == USER_ID

    def test_empty_config(self):
        _get_context = self._import()
        # None config should use empty dicts
        with pytest.raises(ValueError):
            _get_context(None)  # type: ignore[arg-type]

    def test_fallback_mode_prefers_subagent_id(self):
        _get_context = self._import()
        config = _make_config(
            configurable={
                "user_id": USER_ID,
                "thread_id": THREAD_ID,
                "subagent_id": "sub-2",
            },
            metadata={"agent_name": AGENT_NAME},
        )
        ctx = _get_context(config)
        assert ctx["written_by"] == "sub-2"
        assert ctx["agent_name"] == "sub-2"


# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    """Tests for _resolve_path."""

    def _import(self):
        from app.agents.tools.vfs_tools import _resolve_path

        return _resolve_path

    def test_empty_path_returns_agent_root(self):
        _resolve_path = self._import()
        result = _resolve_path("", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor"

    def test_dot_returns_agent_root(self):
        _resolve_path = self._import()
        result = _resolve_path(".", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor"

    def test_users_prefix_without_slash(self):
        _resolve_path = self._import()
        result = _resolve_path(
            f"users/{USER_ID}/global/executor/notes/file.txt", USER_ID
        )
        assert result == f"/users/{USER_ID}/global/executor/notes/file.txt"

    def test_absolute_user_path_validated(self):
        _resolve_path = self._import()
        result = _resolve_path(f"/users/{USER_ID}/global/executor/files/a.txt", USER_ID)
        assert result == f"/users/{USER_ID}/global/executor/files/a.txt"

    def test_system_path_passes_through(self):
        _resolve_path = self._import()
        result = _resolve_path("/system/skills/agent/skill", USER_ID)
        assert result == "/system/skills/agent/skill"

    def test_user_visible_path_with_conversation(self):
        _resolve_path = self._import()
        result = _resolve_path(".user-visible/report.md", USER_ID, "executor", "conv1")
        assert "/sessions/conv1/.user-visible/report.md" in result

    def test_user_visible_folder_only_with_conversation(self):
        _resolve_path = self._import()
        result = _resolve_path(".user-visible", USER_ID, "executor", "conv1")
        assert "/sessions/conv1/.user-visible" in result

    def test_user_visible_without_conversation_falls_back(self):
        _resolve_path = self._import()
        result = _resolve_path(".user-visible/report.md", USER_ID, "executor", None)
        assert "/files/report.md" in result

    def test_user_visible_folder_only_without_conversation(self):
        _resolve_path = self._import()
        result = _resolve_path(".user-visible", USER_ID, "executor", None)
        assert "/files" in result

    def test_relative_known_folder_notes(self):
        _resolve_path = self._import()
        result = _resolve_path("notes/meeting.txt", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor/notes/meeting.txt"

    def test_relative_known_folder_files(self):
        _resolve_path = self._import()
        result = _resolve_path("files/data.json", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor/files/data.json"

    def test_relative_known_folder_sessions(self):
        _resolve_path = self._import()
        result = _resolve_path("sessions/abc/out.json", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor/sessions/abc/out.json"

    def test_plain_filename_defaults_to_files(self):
        _resolve_path = self._import()
        result = _resolve_path("data.json", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor/files/data.json"

    def test_leading_slash_relative_to_agent_root(self):
        _resolve_path = self._import()
        result = _resolve_path("/custom/path.txt", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor/custom/path.txt"

    def test_whitespace_stripped(self):
        _resolve_path = self._import()
        result = _resolve_path("  notes/a.txt  ", USER_ID, "executor")
        assert result == f"/users/{USER_ID}/global/executor/notes/a.txt"

    def test_access_denied_other_user_falls_through(self):
        """Accessing another user's path logs warning and falls through to default handler."""
        _resolve_path = self._import()
        # Path for a different user - access denied, falls through to leading-slash handler
        result = _resolve_path(
            "/users/other_user/global/executor/notes/a.txt", USER_ID, "executor"
        )
        # The path starts with / so after the access-denied warning it's treated
        # as relative to agent root: agent_root + path
        assert result.startswith(f"/users/{USER_ID}/")


# ---------------------------------------------------------------------------
# _emit_artifact_event
# ---------------------------------------------------------------------------


class TestEmitArtifactEvent:
    """Tests for _emit_artifact_event."""

    async def test_non_user_visible_path_is_noop(self):
        from app.agents.tools.vfs_tools import _emit_artifact_event

        mock_vfs = AsyncMock()
        # Should return immediately without calling get_stream_writer
        with patch("app.agents.tools.vfs_tools.get_stream_writer") as mock_writer:
            await _emit_artifact_event(
                path="/users/u1/global/executor/files/a.txt",
                user_id="u1",
                vfs=mock_vfs,
            )
            mock_writer.assert_not_called()

    async def test_user_visible_path_emits_event(self):
        from app.agents.tools.vfs_tools import _emit_artifact_event

        mock_vfs = AsyncMock()
        info_mock = MagicMock()
        info_mock.size_bytes = 42
        mock_vfs.info.return_value = info_mock

        writer_fn = MagicMock()
        with patch(
            "app.agents.tools.vfs_tools.get_stream_writer", return_value=writer_fn
        ):
            await _emit_artifact_event(
                path="/users/u1/global/executor/sessions/c1/.user-visible/report.md",
                user_id="u1",
                vfs=mock_vfs,
            )
            writer_fn.assert_called_once()
            data = writer_fn.call_args[0][0]
            assert "artifact_data" in data
            assert data["artifact_data"]["filename"] == "report.md"
            assert data["artifact_data"]["content_type"] == "text/markdown"
            assert data["artifact_data"]["size_bytes"] == 42

    async def test_user_visible_path_uses_fallback_size(self):
        from app.agents.tools.vfs_tools import _emit_artifact_event

        mock_vfs = AsyncMock()
        mock_vfs.info.side_effect = Exception("not found")

        writer_fn = MagicMock()
        with patch(
            "app.agents.tools.vfs_tools.get_stream_writer", return_value=writer_fn
        ):
            await _emit_artifact_event(
                path="/users/u1/global/executor/sessions/c1/.user-visible/data.json",
                user_id="u1",
                vfs=mock_vfs,
                fallback_size_bytes=100,
            )
            data = writer_fn.call_args[0][0]
            assert data["artifact_data"]["size_bytes"] == 100

    async def test_no_stream_writer_does_not_raise(self):
        from app.agents.tools.vfs_tools import _emit_artifact_event

        mock_vfs = AsyncMock()
        with patch(
            "app.agents.tools.vfs_tools.get_stream_writer",
            side_effect=RuntimeError("no writer"),
        ):
            # Should not raise
            await _emit_artifact_event(
                path="/users/u1/global/executor/sessions/c1/.user-visible/f.txt",
                user_id="u1",
                vfs=mock_vfs,
            )

    async def test_info_returns_none_size(self):
        from app.agents.tools.vfs_tools import _emit_artifact_event

        mock_vfs = AsyncMock()
        info_mock = MagicMock()
        info_mock.size_bytes = None
        mock_vfs.info.return_value = info_mock

        writer_fn = MagicMock()
        with patch(
            "app.agents.tools.vfs_tools.get_stream_writer", return_value=writer_fn
        ):
            await _emit_artifact_event(
                path="/users/u1/global/executor/sessions/c1/.user-visible/f.txt",
                user_id="u1",
                vfs=mock_vfs,
                fallback_size_bytes=55,
            )
            data = writer_fn.call_args[0][0]
            assert data["artifact_data"]["size_bytes"] == 55


# ---------------------------------------------------------------------------
# vfs_read tool
# ---------------------------------------------------------------------------


class TestVfsRead:
    """Tests for the vfs_read tool function."""

    def _make_ctx(self, user_id: str = USER_ID) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "conversation_id": "conv1",
            "agent_name": "executor",
            "written_by": "executor",
            "agent_thread_id": "t1",
            "vfs_session_id": None,
        }

    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_read_success(self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock):
        from app.agents.tools.vfs_tools import vfs_read

        mock_ctx.return_value = self._make_ctx()
        mock_vfs = AsyncMock()
        mock_vfs.read.return_value = "hello world"
        mock_get_vfs.return_value = mock_vfs

        result = await vfs_read.ainvoke(
            {"path": "notes/test.txt"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert result == "hello world"

    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_read_file_not_found(
        self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock
    ):
        from app.agents.tools.vfs_tools import vfs_read

        mock_ctx.return_value = self._make_ctx()
        mock_vfs = AsyncMock()
        mock_vfs.read.return_value = None
        mock_get_vfs.return_value = mock_vfs

        result = await vfs_read.ainvoke(
            {"path": "notes/missing.txt"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "not found" in result.lower()

    @patch("app.agents.tools.vfs_tools._get_context")
    async def test_read_no_user_id(self, mock_ctx: MagicMock):
        from app.agents.tools.vfs_tools import vfs_read

        mock_ctx.return_value = self._make_ctx(user_id=None)  # type: ignore[arg-type]

        result = await vfs_read.ainvoke(
            {"path": "notes/a.txt"},
            config={
                "configurable": {"thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "User ID not found" in result

    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_read_exception(self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock):
        from app.agents.tools.vfs_tools import vfs_read

        mock_ctx.return_value = self._make_ctx()
        mock_get_vfs.side_effect = RuntimeError("db down")

        result = await vfs_read.ainvoke(
            {"path": "notes/a.txt"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "Error reading file" in result


# ---------------------------------------------------------------------------
# vfs_write tool
# ---------------------------------------------------------------------------


class TestVfsWrite:
    """Tests for the vfs_write tool function."""

    def _make_ctx(self, user_id: str = USER_ID) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "conversation_id": "conv1",
            "agent_name": "executor",
            "written_by": "executor",
            "agent_thread_id": "t1",
            "vfs_session_id": None,
        }

    @patch("app.agents.tools.vfs_tools._emit_artifact_event", new_callable=AsyncMock)
    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_write_success(
        self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock, mock_emit: AsyncMock
    ):
        from app.agents.tools.vfs_tools import vfs_write

        mock_ctx.return_value = self._make_ctx()
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        result = await vfs_write.ainvoke(
            {"path": "notes/test.txt", "content": "hello"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "Wrote 5 characters" in result
        mock_vfs.write.assert_awaited_once()

    @patch("app.agents.tools.vfs_tools._emit_artifact_event", new_callable=AsyncMock)
    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_write_append(
        self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock, mock_emit: AsyncMock
    ):
        from app.agents.tools.vfs_tools import vfs_write

        mock_ctx.return_value = self._make_ctx()
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        result = await vfs_write.ainvoke(
            {"path": "notes/log.txt", "content": "new line\n", "append": True},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "Appended" in result
        mock_vfs.append.assert_awaited_once()

    @patch("app.agents.tools.vfs_tools._get_context")
    async def test_write_no_user_id(self, mock_ctx: MagicMock):
        from app.agents.tools.vfs_tools import vfs_write

        mock_ctx.return_value = self._make_ctx(user_id=None)  # type: ignore[arg-type]

        result = await vfs_write.ainvoke(
            {"path": "a.txt", "content": "x"},
            config={
                "configurable": {"thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "User ID not found" in result

    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_write_exception(self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock):
        from app.agents.tools.vfs_tools import vfs_write

        mock_ctx.return_value = self._make_ctx()
        mock_get_vfs.side_effect = RuntimeError("db down")

        result = await vfs_write.ainvoke(
            {"path": "a.txt", "content": "x"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "Error writing file" in result

    @patch("app.agents.tools.vfs_tools._emit_artifact_event", new_callable=AsyncMock)
    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs")
    async def test_write_metadata_includes_session(
        self, mock_get_vfs: AsyncMock, mock_ctx: MagicMock, mock_emit: AsyncMock
    ):
        from app.agents.tools.vfs_tools import vfs_write

        ctx = self._make_ctx()
        ctx["vfs_session_id"] = "shared-session"
        mock_ctx.return_value = ctx
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs

        await vfs_write.ainvoke(
            {"path": "notes/test.txt", "content": "data"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        call_args = mock_vfs.write.call_args
        metadata = call_args[0][3]
        assert metadata["vfs_session_id"] == "shared-session"


# ---------------------------------------------------------------------------
# vfs_cmd tool
# ---------------------------------------------------------------------------


class TestVfsCmd:
    """Tests for the vfs_cmd tool function."""

    def _make_ctx(self, user_id: str = USER_ID) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "conversation_id": "conv1",
            "agent_name": "executor",
            "written_by": "executor",
            "agent_thread_id": "t1",
            "vfs_session_id": None,
        }

    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs_command_parser")
    async def test_cmd_success(
        self, mock_parser_factory: MagicMock, mock_ctx: MagicMock
    ):
        from app.agents.tools.vfs_tools import vfs_cmd

        mock_ctx.return_value = self._make_ctx()
        mock_parser = MagicMock()
        mock_parser.execute = AsyncMock(return_value="file1.txt\nfile2.txt")
        mock_parser_factory.return_value = mock_parser

        result = await vfs_cmd.ainvoke(
            {"command": "ls notes/"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "file1.txt" in result

    @patch("app.agents.tools.vfs_tools._get_context")
    async def test_cmd_no_user_id(self, mock_ctx: MagicMock):
        from app.agents.tools.vfs_tools import vfs_cmd

        mock_ctx.return_value = self._make_ctx(user_id=None)  # type: ignore[arg-type]

        result = await vfs_cmd.ainvoke(
            {"command": "ls"},
            config={
                "configurable": {"thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "User ID not found" in result

    @patch("app.agents.tools.vfs_tools._get_context")
    @patch("app.agents.tools.vfs_tools.get_vfs_command_parser")
    async def test_cmd_exception(
        self, mock_parser_factory: MagicMock, mock_ctx: MagicMock
    ):
        from app.agents.tools.vfs_tools import vfs_cmd

        mock_ctx.return_value = self._make_ctx()
        mock_parser_factory.side_effect = RuntimeError("boom")

        result = await vfs_cmd.ainvoke(
            {"command": "ls"},
            config={
                "configurable": {"user_id": USER_ID, "thread_id": "t1"},
                "metadata": {"agent_name": "executor"},
            },
        )
        assert "Error executing command" in result


# ---------------------------------------------------------------------------
# file_tools: query_file, _get_similar_documents, _construct_content
# ---------------------------------------------------------------------------


class TestConstructContent:
    """Tests for _construct_content."""

    def _import(self):
        from app.agents.tools.file_tools import _construct_content

        return _construct_content

    def _make_doc(
        self, file_id: str, page_wise_summary: Any, description: str = "desc"
    ):
        return {
            "file_id": file_id,
            "page_wise_summary": page_wise_summary,
            "description": description,
        }

    def _make_similar(self, file_id: str, page_number: int = 1, score: float = 0.9):
        from langchain_core.documents import Document

        doc = Document(
            page_content="content",
            metadata={"file_id": file_id, "page_number": page_number},
        )
        return (doc, score)

    def test_no_page_wise_summary(self):
        _construct_content = self._import()
        docs = [self._make_doc("f1", None, "my desc")]
        similar = [self._make_similar("f1")]
        result = _construct_content(docs, similar)
        assert "f1" in result
        assert "my desc" in result

    def test_string_summary(self):
        _construct_content = self._import()
        docs = [self._make_doc("f1", "summary text")]
        similar = [self._make_similar("f1")]
        result = _construct_content(docs, similar)
        assert "summary text" in result

    def test_list_summary_matching_page(self):
        _construct_content = self._import()
        pages = [{"data": {"page_number": 2, "content": "page two content"}}]
        docs = [self._make_doc("f1", pages)]
        similar = [self._make_similar("f1", page_number=2)]
        result = _construct_content(docs, similar)
        assert "page two content" in result

    def test_list_summary_no_matching_page(self):
        _construct_content = self._import()
        pages = [{"data": {"page_number": 5, "content": "page five"}}]
        docs = [self._make_doc("f1", pages)]
        similar = [self._make_similar("f1", page_number=2)]
        result = _construct_content(docs, similar)
        # No matching page, should not include page five content via break
        assert "page five" not in result

    def test_dict_summary(self):
        _construct_content = self._import()
        docs = [self._make_doc("f1", {"data": {"content": "dict content"}})]
        similar = [self._make_similar("f1")]
        result = _construct_content(docs, similar)
        assert "dict content" in result

    def test_dict_summary_missing_data(self):
        _construct_content = self._import()
        docs = [self._make_doc("f1", {"other": "val"})]
        similar = [self._make_similar("f1")]
        result = _construct_content(docs, similar)
        assert "Description not available!" in result

    def test_unexpected_type(self):
        _construct_content = self._import()
        docs = [self._make_doc("f1", 12345)]
        similar = [self._make_similar("f1")]
        result = _construct_content(docs, similar)
        assert "Invalid format" in result

    def test_missing_document(self):
        _construct_content = self._import()
        docs = []  # no matching document
        similar = [self._make_similar("f1")]
        result = _construct_content(docs, similar)
        assert result == ""


class TestGetSimilarDocuments:
    """Tests for _get_similar_documents."""

    @patch("app.agents.tools.file_tools.ChromaClient.get_langchain_client")
    async def test_returns_empty_when_client_none(self, mock_get_client: AsyncMock):
        from app.agents.tools.file_tools import _get_similar_documents

        mock_get_client.return_value = None
        result = await _get_similar_documents("query", "conv1", "user1")
        assert result == []

    @patch("app.agents.tools.file_tools.ChromaClient.get_langchain_client")
    async def test_returns_results_with_file_id_filter(
        self, mock_get_client: AsyncMock
    ):
        from app.agents.tools.file_tools import _get_similar_documents

        mock_collection = AsyncMock()
        expected = [("doc", 0.9)]
        mock_collection.asimilarity_search_with_score.return_value = expected
        mock_get_client.return_value = mock_collection

        result = await _get_similar_documents("query", "conv1", "user1", file_id="f1")
        assert result == expected
        call_kwargs = mock_collection.asimilarity_search_with_score.call_args[1]
        # Verify filter includes file_id
        and_clauses = call_kwargs["filter"]["$and"]
        assert any(c.get("file_id") == "f1" for c in and_clauses)

    @patch("app.agents.tools.file_tools.ChromaClient.get_langchain_client")
    async def test_returns_results_without_file_id(self, mock_get_client: AsyncMock):
        from app.agents.tools.file_tools import _get_similar_documents

        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score.return_value = []
        mock_get_client.return_value = mock_collection

        result = await _get_similar_documents("query", "conv1", "user1")
        assert result == []
        call_kwargs = mock_collection.asimilarity_search_with_score.call_args[1]
        and_clauses = call_kwargs["filter"]["$and"]
        assert len(and_clauses) == 1  # only user_id


class TestQueryFile:
    """Tests for the query_file tool."""

    @patch("app.agents.tools.file_tools.files_collection")
    @patch("app.agents.tools.file_tools._get_similar_documents")
    async def test_query_file_success(
        self, mock_similar: AsyncMock, mock_files: MagicMock
    ):
        from app.agents.tools.file_tools import query_file

        from langchain_core.documents import Document

        sim_doc = Document(
            page_content="text",
            metadata={"file_id": "f1", "page_number": 1},
        )
        mock_similar.return_value = [(sim_doc, 0.9)]

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "file_id": "f1",
                    "page_wise_summary": "summary",
                    "description": "desc",
                }
            ]
        )
        mock_files.find.return_value = mock_cursor

        result = await query_file.ainvoke(
            {"query": "test query", "file_id": "f1"},
            config={
                "configurable": {"thread_id": "t1", "user_id": "u1"},
                "metadata": {},
            },
        )
        assert "summary" in result

    async def test_query_file_no_configurable(self):
        from app.agents.tools.file_tools import query_file

        with pytest.raises(ValueError, match="Configurable is not set"):
            await query_file.ainvoke(
                {"query": "test", "file_id": None},
                config={"metadata": {}},
            )
