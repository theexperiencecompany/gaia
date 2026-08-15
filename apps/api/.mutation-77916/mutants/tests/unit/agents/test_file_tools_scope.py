"""``search_uploaded_files`` must scope by the conversation, not the graph thread.

The tool is registered for the executor only (``registry.py`` "documents"
category), and ``prepare_executor_execution`` runs the executor on a derived
thread ``executor_<conversation_id>``. Reading the conversation scope out of
``thread_id`` therefore looked up a conversation that owns no files, so the tool
returned an empty string for every upload — the executor's only route to an
uploaded file's extracted content. ``build_agent_config`` documents the trap:
the true conversation id is not recoverable from ``thread_id``.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.file_tools import search_uploaded_files

CONVERSATION_ID = "conv-abc123"
EXECUTOR_THREAD_ID = f"executor_{CONVERSATION_ID}"
USER_ID = "user-1"


def _executor_config() -> dict[str, object]:
    """A configurable shaped exactly as prepare_executor_execution builds it."""
    return {
        "configurable": {
            "thread_id": EXECUTOR_THREAD_ID,
            "conversation_id": CONVERSATION_ID,
            "user_id": USER_ID,
        }
    }


@pytest.mark.unit
class TestSearchUploadedFilesScope:
    async def test_looks_up_files_by_conversation_id_not_thread_id(self):
        """The Mongo scope query must receive the conversation id."""
        find_ids = AsyncMock(return_value=[])
        with (
            patch(
                "app.agents.tools.file_tools.ChromaClient.get_langchain_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "app.agents.tools.file_tools.file_repository.find_ids_for_conversation",
                find_ids,
            ),
        ):
            await search_uploaded_files.ainvoke(
                {"query": "oldest blu-ray", "file_id": None},
                config=_executor_config(),
            )

        find_ids.assert_awaited_once_with(CONVERSATION_ID, USER_ID)

    async def test_returns_the_uploaded_file_content_for_an_executor_thread(self):
        """End to end through the tool: an executor thread still finds the upload.

        Fails whenever the scope id regresses to ``thread_id`` — the lookup then
        matches no file and the tool hands the agent an empty string.
        """
        chroma_document = type("Doc", (), {"metadata": {"file_id": "file-1", "page_number": 1}})()
        chroma = AsyncMock()
        chroma.asimilarity_search_with_score = AsyncMock(return_value=[(chroma_document, 0.1)])
        stored = type(
            "FileDoc",
            (),
            {
                "file_id": "file-1",
                "description": "Inventory list",
                "page_wise_summary": [
                    {"data": {"page_number": 1, "content": "| Time-Parking 2 | 2009 |"}}
                ],
            },
        )()

        async def _find_ids(conversation_id: str, user_id: str) -> list[str]:
            return ["file-1"] if conversation_id == CONVERSATION_ID else []

        with (
            patch(
                "app.agents.tools.file_tools.ChromaClient.get_langchain_client",
                AsyncMock(return_value=chroma),
            ),
            patch(
                "app.agents.tools.file_tools.file_repository.find_ids_for_conversation",
                _find_ids,
            ),
            patch(
                "app.agents.tools.file_tools.file_repository.find_by_ids_for_user",
                AsyncMock(return_value=[stored]),
            ),
        ):
            content = await search_uploaded_files.ainvoke(
                {"query": "oldest blu-ray", "file_id": None},
                config=_executor_config(),
            )

        assert "Time-Parking 2" in content

    async def test_an_unknown_file_id_fails_loud_instead_of_returning_nothing(self):
        """An id the conversation does not own must not read as "no matches".

        Proven against the live stack: passing the filename — the only file
        identifier the agent is ever shown — returned "" silently, which the
        model cannot distinguish from an empty document.
        """
        with (
            patch(
                "app.agents.tools.file_tools.ChromaClient.get_langchain_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "app.agents.tools.file_tools.file_repository.find_ids_for_conversation",
                AsyncMock(return_value=["file-1"]),
            ),
            pytest.raises(ValueError, match="inventory.xlsx"),
        ):
            await search_uploaded_files.ainvoke(
                {"query": "oldest blu-ray", "file_id": "inventory.xlsx"},
                config=_executor_config(),
            )
