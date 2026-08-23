"""Onboarding gate: can a model actually see an image delivered in a tool result?

Run this before adding an OpenRouter-inference model to
``OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT`` (``constants/llm.py``). It costs real
tokens, so it is marked
``model_onboarding`` and excluded from the default suite.

    # check a candidate before declaring it
    GAIA_ONBOARD_MODELS=x-ai/grok-4.1-fast \
      uv run pytest tests/model_onboarding -m model_onboarding -v

    # re-check everything already declared
    uv run pytest tests/model_onboarding -m model_onboarding -v

Why a live call and not a capability lookup: OpenRouter exposes nothing that
answers this. `/api/v1/models` reports `architecture.input_modalities` (whether
the model takes images *at all*) and `/models/:id/endpoints` reports uptime and
pricing — neither says whether images survive in a *tool* message. Two models
can be byte-identical there and still disagree: `openai/gpt-5-mini` accepts it,
`openai/gpt-4o-mini` returns
``"Image URLs are only allowed for messages with role 'user'"``. So the only
honest test is to send one and see whether the model describes the picture.

A failure means `MediaDelivery.KEEP_IN_TOOL_RESULTS` is wrong for that model:
its tool results would 400 mid-turn. Do not declare it — raise it, and decide
then whether the model is worth a per-model delivery path.
"""

import base64
import io
import os

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openrouter import ChatOpenRouter
from PIL import Image
import pytest

from app.config.settings import settings
from app.constants.llm import OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT

# Applies openrouter_tool_multimodal_patch: the client library converts media
# blocks for user messages but not for tool messages, so without this the SDK
# rejects the payload locally and the test would never reach the model.
import app.patches  # noqa: F401

pytestmark = pytest.mark.model_onboarding

_BACKGROUND = (128, 0, 160)  # purple
_FOREGROUND = (255, 220, 0)  # yellow


def _declared_openrouter_models() -> list[str]:
    """Read straight from the constants — never keep a model list in this file.

    A new model is declared in one place, ``OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT``
    in ``constants/llm.py``, and this test picks it up from there. A copy here
    would drift the moment someone declares a model without touching the tests,
    and the model this gate exists to catch would be the one it silently skips.

    Text-only models are exempt BY DECLARATION, not by omission: a ``False``
    routes tool media through the caption fallback, so asserting those models
    see pixels would fail by design. The flag lives on the declaration so a
    model can only skip this gate by saying so out loud.
    """
    return [
        model_id
        for model_id, sees_tool_images in OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT.items()
        if sees_tool_images
    ]


def _models_under_test() -> list[str]:
    """Declared models by default; ``GAIA_ONBOARD_MODELS`` to vet one first.

    The override is for the order this actually happens in — you check a
    candidate first, then add it to the constants once it passes.
    """
    override = os.environ.get("GAIA_ONBOARD_MODELS", "").strip()
    if override:
        return [name.strip() for name in override.split(",") if name.strip()]
    return _declared_openrouter_models()


def _two_colour_png() -> str:
    """A yellow square on purple — two colours the model must name to prove it saw it."""
    image = Image.new("RGB", (120, 120), _BACKGROUND)
    for y in range(40, 80):
        for x in range(40, 80):
            image.putpixel((x, y), _FOREGROUND)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


@pytest.mark.skipif(not settings.OPENROUTER_API_KEY, reason="OPENROUTER_API_KEY is not configured")
@pytest.mark.parametrize("model", _models_under_test())
def test_model_sees_an_image_returned_by_a_tool(model: str) -> None:
    """The exact shape our agent produces: a `read` tool result carrying pixels.

    Asserted on content, not status: a 200 that describes the wrong thing means
    the image was dropped somewhere in the chain, which is the failure this gate
    exists to catch.
    """
    llm = ChatOpenRouter(model=model, api_key=settings.OPENROUTER_API_KEY, temperature=0)
    messages = [
        HumanMessage(content="What are the two colours in the image? Answer in under 10 words."),
        AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "call_1"}]),
        ToolMessage(
            content=[
                {"type": "text", "text": "Image file /workspace/shot.png"},
                # The canonical block ImageCodec emits for every media producer.
                {"type": "image", "base64": _two_colour_png(), "mime_type": "image/png"},
            ],
            tool_call_id="call_1",
            name="read",
        ),
    ]

    answer = llm.invoke(messages).text.lower()

    assert "purple" in answer and "yellow" in answer, (
        f"{model} did not perceive an image delivered in a tool result (answered: {answer!r}). "
        f"KEEP_IN_TOOL_RESULTS is unsafe for it — do not seed it without a delivery path."
    )
