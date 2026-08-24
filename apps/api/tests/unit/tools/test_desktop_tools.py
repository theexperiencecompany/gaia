"""Behavior tests for app.agents.tools.desktop_tools.

Locks: desktop-only gating (a non-desktop source is refused with the
not-desktop error), the stream/user context guard, the bridge outcome shapes
(error strings for the LLM on failure), screenshot persistence with graceful
degradation when the workspace write fails, and the window list formatting.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.tools.desktop_tools import (
    _MISSING_CONTEXT_ERROR,
    _NOT_DESKTOP_ERROR,
    list_windows,
    open_app,
    open_url,
    read_clipboard,
    take_screenshot,
    write_clipboard,
)
from app.services.desktop.bridge import DesktopToolOutcome
from app.utils.image_codec import InlineImage

MODULE = "app.agents.tools.desktop_tools"

STREAM_ID = "stream-1"
USER_ID = "user-1"


def _config(source: str = "desktop") -> dict[str, Any]:
    return {
        "configurable": {
            "conversation_source": source,
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": "conv-1",
        }
    }


def _desktop_config() -> dict[str, Any]:
    return _config("desktop")


class TestDesktopGating:
    async def test_non_desktop_source_is_refused(self) -> None:
        with patch(f"{MODULE}.request_desktop_action", AsyncMock()) as action:
            result = await read_clipboard.coroutine(config=_config("web"))

        assert result == _NOT_DESKTOP_ERROR
        action.assert_not_called()

    async def test_missing_stream_context_is_refused(self) -> None:
        config = _desktop_config()
        config["configurable"].pop("stream_id")
        with patch(f"{MODULE}.request_desktop_action", AsyncMock()) as action:
            result = await read_clipboard.coroutine(config=config)

        assert result == _MISSING_CONTEXT_ERROR
        action.assert_not_called()

    async def test_missing_user_id_is_refused(self) -> None:
        config = _desktop_config()
        config["configurable"].pop("user_id")
        with patch(f"{MODULE}.request_desktop_action", AsyncMock()) as action:
            result = await read_clipboard.coroutine(config=config)

        assert result == _MISSING_CONTEXT_ERROR
        action.assert_not_called()


class TestReadClipboard:
    async def test_happy_path_returns_the_text(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=True, data={"text": "copied!"})),
        ):
            result = await read_clipboard.coroutine(config=_desktop_config())

        assert result == "Clipboard contents:\ncopied!"

    async def test_empty_clipboard_is_reported(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=True, data={"text": ""})),
        ):
            result = await read_clipboard.coroutine(config=_desktop_config())

        assert result == "The clipboard is empty (or contains non-text content)."

    async def test_bridge_failure_returns_an_error_string(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=False, error="app not open")),
        ):
            result = await read_clipboard.coroutine(config=_desktop_config())

        assert result == "Could not read the clipboard: app not open"


class TestWriteClipboard:
    async def test_happy_path(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=True)),
        ) as action:
            result = await write_clipboard.coroutine(config=_desktop_config(), text="hi")

        assert result == "Copied to the user's clipboard."
        action.assert_awaited_once()
        assert action.await_args.kwargs["tool"] == "write_clipboard"
        assert action.await_args.kwargs["params"] == {"text": "hi"}

    async def test_failure_returns_an_error_string(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=False, error="nope")),
        ):
            result = await write_clipboard.coroutine(config=_desktop_config(), text="hi")

        assert result == "Could not write to the clipboard: nope"


class TestOpenApp:
    async def test_happy_path(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=True)),
        ):
            result = await open_app.coroutine(config=_desktop_config(), app_name="Safari")

        assert result == "Opened Safari on the user's computer."

    async def test_failure_names_the_app(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=False, error="no such app")),
        ):
            result = await open_app.coroutine(config=_desktop_config(), app_name="Safari")

        assert result == "Could not open 'Safari': no such app"


class TestOpenUrl:
    async def test_happy_path(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=True)),
        ):
            result = await open_url.coroutine(config=_desktop_config(), url="https://gaia.local")

        assert result == "Opened https://gaia.local in the user's default browser."

    async def test_failure_returns_an_error_string(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=False, error="blocked")),
        ):
            result = await open_url.coroutine(config=_desktop_config(), url="https://gaia.local")

        assert result == "Could not open the URL: blocked"


class TestListWindows:
    async def test_formats_windows_with_fallbacks(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(
                return_value=DesktopToolOutcome(
                    ok=True,
                    data={
                        "windows": [
                            {"app": "Safari", "title": "GAIA"},
                            {"app": "Notes", "title": None},
                            {"title": "Untitled doc"},
                        ]
                    },
                )
            ),
        ):
            result = await list_windows.coroutine(config=_desktop_config())

        assert "- Safari: GAIA" in result
        assert "- Notes: (untitled)" in result
        assert "- Unknown app: Untitled doc" in result

    async def test_no_windows_is_reported(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=True, data={"windows": []})),
        ):
            result = await list_windows.coroutine(config=_desktop_config())

        assert result == "No open windows were reported."

    async def test_failure_returns_an_error_string(self) -> None:
        with patch(
            f"{MODULE}.request_desktop_action",
            AsyncMock(return_value=DesktopToolOutcome(ok=False, error="bridge down")),
        ):
            result = await list_windows.coroutine(config=_desktop_config())

        assert result == "Could not list windows: bridge down"


class TestTakeScreenshot:
    def _image(self) -> InlineImage:
        return InlineImage(data=b"png-bytes", base64="cG5n", mime_type="image/png")

    async def test_happy_path_returns_text_and_image_blocks(self) -> None:
        writer = MagicMock()
        with (
            patch(f"{MODULE}.get_stream_writer", MagicMock(return_value=writer)),
            patch(
                f"{MODULE}.request_desktop_action",
                AsyncMock(
                    return_value=DesktopToolOutcome(
                        ok=True,
                        data={
                            "image_b64": "cG5n",
                            "thumbnail_b64": "dGh1bWI=",
                            "width": 800,
                            "height": 600,
                        },
                    )
                ),
            ),
            patch(
                f"{MODULE}.ImageCodec.from_base64", AsyncMock(return_value=self._image())
            ) as codec,
            patch(
                f"{MODULE}.write_session_file",
                AsyncMock(return_value=("", "/workspace/screenshots/shot.png")),
            ) as save,
        ):
            result = await take_screenshot.coroutine(config=_desktop_config(), query="find the bug")

        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert "saved to /workspace/screenshots/shot.png" in result[0]["text"]
        assert "find the bug" in result[0]["text"]
        assert result[1]["type"] == "image"
        codec.assert_awaited_once_with("cG5n")
        save.assert_awaited_once()
        # The thumbnail card was streamed for the UI.
        streamed = [c.args[0] for c in writer.call_args_list]
        assert any(
            "screenshot_data" in e.get("tool_data", {}).get("tool_name", "") for e in streamed
        )

    async def test_failed_bridge_returns_an_error_string(self) -> None:
        with (
            patch(f"{MODULE}.get_stream_writer", MagicMock()),
            patch(
                f"{MODULE}.request_desktop_action",
                AsyncMock(return_value=DesktopToolOutcome(ok=False, error="no permission")),
            ),
        ):
            result = await take_screenshot.coroutine(config=_desktop_config(), query="look")

        assert result == "Could not capture the screen: no permission"

    async def test_missing_image_data_is_reported(self) -> None:
        with (
            patch(f"{MODULE}.get_stream_writer", MagicMock()),
            patch(
                f"{MODULE}.request_desktop_action",
                AsyncMock(return_value=DesktopToolOutcome(ok=True, data={"image_b64": None})),
            ),
        ):
            result = await take_screenshot.coroutine(config=_desktop_config(), query="look")

        assert result == "Could not capture the screen: the desktop app returned no image."

    async def test_empty_outcome_data_is_an_unknown_error(self) -> None:
        with (
            patch(f"{MODULE}.get_stream_writer", MagicMock()),
            patch(
                f"{MODULE}.request_desktop_action",
                AsyncMock(return_value=DesktopToolOutcome(ok=True, data={})),
            ),
        ):
            result = await take_screenshot.coroutine(config=_desktop_config(), query="look")

        assert result == "Could not capture the screen: unknown error"

    async def test_invalid_image_data_returns_an_error_string(self) -> None:
        from app.utils.image_codec import InvalidImageError

        with (
            patch(f"{MODULE}.get_stream_writer", MagicMock()),
            patch(
                f"{MODULE}.request_desktop_action",
                AsyncMock(return_value=DesktopToolOutcome(ok=True, data={"image_b64": "garbage"})),
            ),
            patch(
                f"{MODULE}.ImageCodec.from_base64", AsyncMock(side_effect=InvalidImageError("bad"))
            ),
        ):
            result = await take_screenshot.coroutine(config=_desktop_config(), query="look")

        assert result.startswith("Could not read the captured screen")

    async def test_workspace_save_failure_still_returns_the_pixels(self) -> None:
        with (
            patch(f"{MODULE}.get_stream_writer", MagicMock()),
            patch(
                f"{MODULE}.request_desktop_action",
                AsyncMock(return_value=DesktopToolOutcome(ok=True, data={"image_b64": "cG5n"})),
            ),
            patch(f"{MODULE}.ImageCodec.from_base64", AsyncMock(return_value=self._image())),
            patch(f"{MODULE}.write_session_file", AsyncMock(side_effect=OSError("no jfs"))),
        ):
            result = await take_screenshot.coroutine(config=_desktop_config(), query="look")

        assert result[0]["type"] == "text"
        assert "not saved to the workspace" in result[0]["text"]
        assert result[1]["type"] == "image"
