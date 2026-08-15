"""Unit tests for app.agents.llm.vision.adapter (MediaAdapter).

The adapter is what stops a provider rejecting the whole turn. Each lane takes
delivery of an image differently, and getting it wrong is not a degraded answer —
it is a 400 that kills the conversation. So these tests assert the shape that
actually reaches the wire, not just that "some media survived".
"""

from collections.abc import Sequence

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agents.llm.vision.adapter import MediaAdapter
from app.agents.llm.vision.capability import MediaDelivery
from app.constants.media import (
    MAX_INLINE_MEDIA_BLOCKS,
    MEDIA_DESCRIPTIONS_KEY,
    MEDIA_EVICTED_NOTICE,
    MEDIA_OMITTED_NOTICE,
)
from app.utils.multimodal import has_media_blocks, media_blocks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _img(tag: str = "A") -> dict:
    return {"type": "image", "base64": f"BASE64-{tag}", "mime_type": "image/png"}


def _tool_msg(*blocks, name: str = "read", call_id: str = "c1", **kwargs) -> ToolMessage:
    return ToolMessage(content=list(blocks), tool_call_id=call_id, name=name, **kwargs)


def _ai_call(call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": call_id}])


def _all_images(messages: Sequence[AnyMessage]) -> list[dict]:
    return [b for m in messages for b in media_blocks(m.content)]


# ---------------------------------------------------------------------------
# Gemini lane: media stays inside the tool result.
# ---------------------------------------------------------------------------


class TestToolMessageBlocksLane:
    def test_image_stays_inside_the_tool_message(self):
        msgs = [_ai_call(), _tool_msg({"type": "text", "text": "shot.png"}, _img())]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)

        assert isinstance(out[1], ToolMessage)
        assert has_media_blocks(out[1].content)
        assert len(out) == len(msgs), "no extra message should be injected on this lane"

    def test_no_human_message_is_injected(self):
        """Repacking into a HumanMessage is the OpenRouter workaround. Doing it on
        Gemini would put a spurious user turn into the conversation."""
        msgs = [_ai_call(), _tool_msg(_img())]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)

        assert not any(isinstance(m, HumanMessage) for m in out)

    def test_messages_without_media_are_returned_untouched(self):
        msgs = [SystemMessage(content="sys"), HumanMessage(content="hi"), AIMessage(content="yo")]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)

        assert out == msgs


# ---------------------------------------------------------------------------
# Text-only lane: prose, and the cached description is what gets spent.
# ---------------------------------------------------------------------------


class TestTextOnlyLane:
    def test_no_image_block_survives(self):
        msgs = [_ai_call(), _tool_msg({"type": "text", "text": "shot.png"}, _img())]

        out = MediaAdapter(MediaDelivery.REPLACE_WITH_TEXT).adapt(msgs)

        assert not _all_images(out)
        assert "BASE64-A" not in str(out[1].content)

    def test_the_cached_description_is_what_the_model_sees(self):
        """describe_tool_media caches the prose at tool-execution time; this lane
        must spend it, not emit a bare notice that tells the model nothing."""
        msg = _tool_msg(
            {"type": "text", "text": "shot.png"},
            _img(),
            additional_kwargs={MEDIA_DESCRIPTIONS_KEY: ["A login screen with a red banner."]},
        )

        out = MediaAdapter(MediaDelivery.REPLACE_WITH_TEXT).adapt([_ai_call(), msg])

        assert "A login screen with a red banner." in out[1].content
        assert MEDIA_OMITTED_NOTICE not in out[1].content

    def test_every_cached_description_is_rendered_not_just_the_first(self):
        msg = _tool_msg(
            _img("A"),
            _img("B"),
            additional_kwargs={MEDIA_DESCRIPTIONS_KEY: ["first image", "second image"]},
        )

        out = MediaAdapter(MediaDelivery.REPLACE_WITH_TEXT).adapt([_ai_call(), msg])

        assert "first image" in out[1].content
        assert "second image" in out[1].content

    def test_a_message_with_no_cached_description_falls_back_to_the_notice(self):
        """Produced on a vision lane, replayed on a text-only one — there is
        nothing to spend, and the model must at least be told it is blind."""
        out = MediaAdapter(MediaDelivery.REPLACE_WITH_TEXT).adapt([_ai_call(), _tool_msg(_img())])

        assert MEDIA_OMITTED_NOTICE in out[1].content

    def test_an_empty_description_list_falls_back_rather_than_rendering_nothing(self):
        msg = _tool_msg(_img(), additional_kwargs={MEDIA_DESCRIPTIONS_KEY: []})

        out = MediaAdapter(MediaDelivery.REPLACE_WITH_TEXT).adapt([_ai_call(), msg])

        assert MEDIA_OMITTED_NOTICE in out[1].content


# ---------------------------------------------------------------------------
# Per-request budget: history is append-only and media is never compacted away.
# ---------------------------------------------------------------------------


class TestBudget:
    def test_at_most_max_blocks_reach_the_provider(self):
        """Without this, a thread that read twenty screenshots re-sends all of
        them on every subsequent turn until the provider rejects the payload."""
        msgs = [
            _tool_msg(_img(str(i)), call_id=f"c{i}") for i in range(MAX_INLINE_MEDIA_BLOCKS + 3)
        ]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)

        assert len(_all_images(out)) == MAX_INLINE_MEDIA_BLOCKS

    def test_the_most_recent_images_win(self):
        """Evicting the newest would drop the image the model just asked to see."""
        msgs = [
            _tool_msg(_img(str(i)), call_id=f"c{i}") for i in range(MAX_INLINE_MEDIA_BLOCKS + 2)
        ]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)
        kept = {b["base64"] for b in _all_images(out)}

        assert "BASE64-0" not in kept, "oldest image should have been evicted"
        newest = f"BASE64-{MAX_INLINE_MEDIA_BLOCKS + 1}"
        assert newest in kept, "newest image must survive"

    def test_an_evicted_message_says_so_instead_of_going_silent(self):
        msgs = [
            _tool_msg(_img(str(i)), call_id=f"c{i}") for i in range(MAX_INLINE_MEDIA_BLOCKS + 1)
        ]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)

        assert any(MEDIA_EVICTED_NOTICE in str(m.content) for m in out)

    def test_exactly_at_the_budget_nothing_is_evicted(self):
        """Boundary: `>=` vs `>` in the budget check."""
        msgs = [_tool_msg(_img(str(i)), call_id=f"c{i}") for i in range(MAX_INLINE_MEDIA_BLOCKS)]

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt(msgs)

        assert len(_all_images(out)) == MAX_INLINE_MEDIA_BLOCKS
        assert not any(MEDIA_EVICTED_NOTICE in str(m.content) for m in out)

    def test_the_budget_counts_blocks_not_messages(self):
        """One tool result carrying many images must still be capped."""
        many = _tool_msg(*[_img(str(i)) for i in range(MAX_INLINE_MEDIA_BLOCKS + 4)])

        out = MediaAdapter(MediaDelivery.KEEP_IN_TOOL_RESULTS).adapt([many])

        assert len(_all_images(out)) == MAX_INLINE_MEDIA_BLOCKS
