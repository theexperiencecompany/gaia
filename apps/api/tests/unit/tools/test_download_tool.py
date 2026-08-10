"""Behavior tests for app.agents.tools.download_tool.

Locks: scheme-less URLs are upgraded to https, downloads land in the session
workspace under a stable hashed name with the extension from URL or content
type, HTML responses are rejected, and every error path returns an "Error:"
string for the LLM instead of raising.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from app.agents.tools.download_tool import download
from app.constants.download import DOWNLOAD_HTML_REJECTED
from app.utils.url_download import (
    DownloadedFile,
    DownloadError,
    download_filename,
    extension_from_url,
)

MODULE = "app.agents.tools.download_tool"

URL = "https://example.com/report.pdf"


def _config() -> dict[str, Any]:
    return {"configurable": {"user_id": "user-1", "conversation_id": "conv-1"}}


def _no_session_config() -> dict[str, Any]:
    return {"configurable": {"user_id": "user-1"}}


class TestDownload:
    async def test_happy_path_writes_the_file_into_the_workspace(self) -> None:
        with (
            patch(
                f"{MODULE}.download_public_url",
                AsyncMock(
                    return_value=DownloadedFile(data=b"%PDF-bytes", content_type="application/pdf")
                ),
            ) as fetch,
            patch(
                f"{MODULE}.write_session_file",
                AsyncMock(return_value=("", "/workspace/downloads/download-hash.pdf")),
            ) as write,
        ):
            result = await download.coroutine(config=_config(), url=URL)

        assert result == "/workspace/downloads/download-hash.pdf"
        fetch.assert_awaited_once_with(URL)
        assert write.await_args.kwargs["user_id"] == "user-1"
        assert write.await_args.kwargs["conversation_id"] == "conv-1"
        expected_name = download_filename(URL, extension_from_url(URL))
        assert write.await_args.kwargs["relative_path"] == f"downloads/{expected_name}"
        assert write.await_args.kwargs["content"] == b"%PDF-bytes"

    async def test_schemeless_url_is_upgraded_to_https(self) -> None:
        with (
            patch(
                f"{MODULE}.download_public_url",
                AsyncMock(return_value=DownloadedFile(data=b"x", content_type="application/pdf")),
            ) as fetch,
            patch(f"{MODULE}.write_session_file", AsyncMock(return_value=("", "/workspace/x"))),
        ):
            await download.coroutine(config=_config(), url="example.com/report.pdf")

        fetch.assert_awaited_once_with("https://example.com/report.pdf")

    async def test_extension_falls_back_to_content_type(self) -> None:
        with (
            patch(
                f"{MODULE}.download_public_url",
                AsyncMock(return_value=DownloadedFile(data=b"x", content_type="text/plain")),
            ),
            patch(
                f"{MODULE}.write_session_file",
                AsyncMock(return_value=("", "/workspace/f.txt")),
            ) as write,
        ):
            await download.coroutine(config=_config(), url="https://example.com/f")

        assert write.await_args.kwargs["relative_path"].endswith(".txt")

    async def test_download_error_returns_an_error_string(self) -> None:
        with (
            patch(f"{MODULE}.download_public_url", AsyncMock(side_effect=DownloadError("blocked"))),
            patch(f"{MODULE}.write_session_file", AsyncMock()) as write,
        ):
            result = await download.coroutine(config=_config(), url=URL)

        assert result == "Error: blocked"
        write.assert_not_called()

    async def test_html_content_is_rejected(self) -> None:
        with (
            patch(
                f"{MODULE}.download_public_url",
                AsyncMock(return_value=DownloadedFile(data=b"<html>", content_type="text/html")),
            ),
            patch(f"{MODULE}.write_session_file", AsyncMock()) as write,
        ):
            result = await download.coroutine(config=_config(), url=URL)

        assert result == DOWNLOAD_HTML_REJECTED.format(content_type="text/html")
        write.assert_not_called()

    async def test_missing_user_id_returns_an_error_string(self) -> None:
        config = {"configurable": {"conversation_id": "conv-1"}}
        with (
            patch(f"{MODULE}.download_public_url", AsyncMock()),
            patch(f"{MODULE}.write_session_file", AsyncMock()),
        ):
            result = await download.coroutine(config=config, url=URL)

        assert result == "Error: user_id not found in RunnableConfig"

    async def test_missing_session_returns_an_error_string(self) -> None:
        with (
            patch(f"{MODULE}.download_public_url", AsyncMock()),
            patch(f"{MODULE}.write_session_file", AsyncMock()),
        ):
            result = await download.coroutine(config=_no_session_config(), url=URL)

        assert result == "Error: download requires a conversation-scoped run"
