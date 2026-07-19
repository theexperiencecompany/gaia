"""Unit tests for app.agents.llm.vision.tool_media and the middleware wrapper.

`describe_tool_media` runs on every tool call in the agent loop, so its no-op
guards are load-bearing: a missed guard means a vision API call (and its latency
and cost) on every plain-text tool result. Its caching is equally load-bearing —
without it the same image is re-described on every turn, forever.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
import pytest

from app.agents.llm.vision.tool_media import describe_tool_media
from app.agents.middleware.media import MediaDescriptionMiddleware
from app.constants.media import MEDIA_DESCRIBE_FAILED, MEDIA_DESCRIPTIONS_KEY
from app.utils.multimodal import has_media_blocks

CONFIG = {"configurable": {"provider": "openrouter", "model": "some-model"}}

_MOD = "app.agents.llm.vision.tool_media"


def _img(tag: str = "A") -> dict:
    return {"type": "image", "base64": f"BASE64-{tag}", "mime_type": "image/png"}


def _tool_msg(*blocks, name: str = "read", **kwargs) -> ToolMessage:
    content = list(blocks) if blocks else "plain text result"
    return ToolMessage(content=content, tool_call_id="c1", name=name, **kwargs)


def _patch_lane(
    *, can_see: bool, description: str | None = "A red login screen."
) -> tuple[Any, Any]:
    """Patch the two boundaries: the lane lookup and the vision API call."""
    return (
        patch(f"{_MOD}.model_can_view_images", AsyncMock(return_value=can_see)),
        patch(f"{_MOD}.describe_image", AsyncMock(return_value=description)),
    )


@pytest.mark.asyncio
@pytest.mark.unit
class TestNoOpGuards:
    async def test_a_plain_text_result_is_not_described(self):
        """Runs on EVERY tool call. Describing here would bill a vision call for
        every bash/grep/search result in the system."""
        lane, vision = _patch_lane(can_see=False)
        with lane, vision as mock_vision:
            assert await describe_tool_media(_tool_msg(), CONFIG) is None
            mock_vision.assert_not_called()

    async def test_a_text_only_block_list_is_not_described(self):
        lane, vision = _patch_lane(can_see=False)
        with lane, vision as mock_vision:
            msg = _tool_msg({"type": "text", "text": "rows: 2"})
            assert await describe_tool_media(msg, CONFIG) is None
            mock_vision.assert_not_called()

    async def test_a_vision_capable_lane_is_not_described(self):
        """The model can see the pixels — prose would be wasted money and latency."""
        lane, vision = _patch_lane(can_see=True)
        with lane, vision as mock_vision:
            assert await describe_tool_media(_tool_msg(_img()), CONFIG) is None
            mock_vision.assert_not_called()

    async def test_an_already_described_message_is_not_described_again(self):
        """Idempotence. This is what stops a re-describe on every turn."""
        msg = _tool_msg(_img(), additional_kwargs={MEDIA_DESCRIPTIONS_KEY: ["already done"]})

        lane, vision = _patch_lane(can_see=False)
        with lane, vision as mock_vision:
            assert await describe_tool_media(msg, CONFIG) is None
            mock_vision.assert_not_called()

    async def test_the_lane_is_not_even_looked_up_for_a_result_without_media(self):
        """The media check must come first — the lane lookup can hit the network
        (the OpenRouter catalog), and 99% of tool results carry no media."""
        with patch(f"{_MOD}.model_can_view_images", AsyncMock()) as mock_lane:
            await describe_tool_media(_tool_msg(), CONFIG)
            mock_lane.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
class TestDescribing:
    async def test_the_description_is_cached_on_the_message(self):
        lane, vision = _patch_lane(can_see=False, description="A red login screen.")
        with lane, vision:
            out = await describe_tool_media(_tool_msg(_img()), CONFIG)

        assert out is not None
        assert out.additional_kwargs[MEDIA_DESCRIPTIONS_KEY] == ["A red login screen."]

    async def test_the_image_block_survives_so_the_thread_stays_portable(self):
        """If the user upgrades to a vision model mid-thread, the pixels must
        still be there. Replacing the block with prose would destroy them."""
        lane, vision = _patch_lane(can_see=False)
        with lane, vision:
            out = await describe_tool_media(_tool_msg(_img()), CONFIG)

        assert has_media_blocks(out.content)

    async def test_every_image_gets_its_own_description_in_block_order(self):
        lane = patch(f"{_MOD}.model_can_view_images", AsyncMock(return_value=False))
        vision = patch(f"{_MOD}.describe_image", AsyncMock(side_effect=["first", "second"]))
        with lane, vision:
            out = await describe_tool_media(_tool_msg(_img("A"), _img("B")), CONFIG)

        assert out.additional_kwargs[MEDIA_DESCRIPTIONS_KEY] == ["first", "second"]

    async def test_the_original_message_is_not_mutated_in_place(self):
        msg = _tool_msg(_img())

        lane, vision = _patch_lane(can_see=False)
        with lane, vision:
            out = await describe_tool_media(msg, CONFIG)

        assert MEDIA_DESCRIPTIONS_KEY not in msg.additional_kwargs
        assert out is not msg

    async def test_existing_additional_kwargs_are_preserved(self):
        """Compaction and other middleware write here too — clobbering their keys
        would silently lose the workspace_path of a spilled output."""
        msg = _tool_msg(_img(), additional_kwargs={"compacted": True})

        lane, vision = _patch_lane(can_see=False)
        with lane, vision:
            out = await describe_tool_media(msg, CONFIG)

        assert out.additional_kwargs["compacted"] is True
        assert MEDIA_DESCRIPTIONS_KEY in out.additional_kwargs

    async def test_the_prompt_carries_the_tool_name_and_the_result_text(self):
        """Without the surrounding text the vision model has no idea what it is
        looking at or why — the old read-tool prompt named the file path."""
        lane = patch(f"{_MOD}.model_can_view_images", AsyncMock(return_value=False))
        vision = patch(f"{_MOD}.describe_image", AsyncMock(return_value="ok"))
        with lane, vision as mock_vision:
            msg = _tool_msg({"type": "text", "text": "Image file /workspace/shot.png"}, _img())
            await describe_tool_media(msg, CONFIG)

        prompt = mock_vision.call_args.kwargs["prompt"]
        assert "read" in prompt
        assert "/workspace/shot.png" in prompt


@pytest.mark.asyncio
@pytest.mark.unit
class TestFailurePaths:
    async def test_a_failed_vision_call_degrades_instead_of_failing_the_tool(self):
        """describe_image returns None when the provider errors. The tool result
        must still come back — the text half is usually the point."""
        lane, vision = _patch_lane(can_see=False, description=None)
        with lane, vision:
            out = await describe_tool_media(_tool_msg(_img()), CONFIG)

        assert out.additional_kwargs[MEDIA_DESCRIPTIONS_KEY] == [MEDIA_DESCRIBE_FAILED]

    async def test_a_partial_failure_keeps_the_descriptions_that_did_succeed(self):
        lane = patch(f"{_MOD}.model_can_view_images", AsyncMock(return_value=False))
        vision = patch(f"{_MOD}.describe_image", AsyncMock(side_effect=["good", None]))
        with lane, vision:
            out = await describe_tool_media(_tool_msg(_img("A"), _img("B")), CONFIG)

        assert out.additional_kwargs[MEDIA_DESCRIPTIONS_KEY] == ["good", MEDIA_DESCRIBE_FAILED]


@pytest.mark.asyncio
@pytest.mark.unit
class TestMediaDescriptionMiddleware:
    async def test_it_describes_the_tool_result_it_wraps(self):
        described = _tool_msg(_img(), additional_kwargs={MEDIA_DESCRIPTIONS_KEY: ["prose"]})

        with patch(
            "app.agents.middleware.media.describe_tool_media",
            AsyncMock(return_value=described),
        ):
            result = await MediaDescriptionMiddleware().awrap_tool_call(
                _request(), AsyncMock(return_value=_tool_msg(_img()))
            )

        assert result.additional_kwargs[MEDIA_DESCRIPTIONS_KEY] == ["prose"]

    async def test_the_original_result_is_returned_when_there_is_nothing_to_do(self):
        original = _tool_msg()

        with patch("app.agents.middleware.media.describe_tool_media", AsyncMock(return_value=None)):
            result = await MediaDescriptionMiddleware().awrap_tool_call(
                _request(), AsyncMock(return_value=original)
            )

        assert result is original

    async def test_a_non_tool_message_result_passes_straight_through(self):
        """A tool returning a Command (handoff, HIL interrupt) must not be touched."""
        command = object()

        with patch("app.agents.middleware.media.describe_tool_media", AsyncMock()) as mock:
            result = await MediaDescriptionMiddleware().awrap_tool_call(
                _request(), AsyncMock(return_value=command)
            )

        assert result is command
        mock.assert_not_called()


class _Runtime:
    config = CONFIG


class _Request:
    runtime = _Runtime()


def _request() -> _Request:
    return _Request()
