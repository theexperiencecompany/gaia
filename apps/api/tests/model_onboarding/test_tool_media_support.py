"""Onboarding gate: can a model actually see an image delivered in a tool result?

Run this before adding an OpenRouter-inference model to
OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT (constants/llm.py):
GAIA_ONBOARD_MODELS=<model> uv run pytest tests/model_onboarding -m model_onboarding -v.
It costs real tokens, so it is marked model_onboarding and excluded by default.

No OpenRouter capability lookup answers this — two models byte-identical on
input_modalities can still disagree (openai/gpt-5-mini accepts an image in a
tool message, openai/gpt-4o-mini rejects it) — so the only honest test is a
live call. A failure means MediaDelivery.KEEP_IN_TOOL_RESULTS is wrong for
that model (its tool results would 400 mid-turn): raise it, don't declare it.
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
import app.patches  # noqa: F401  # imported for patch registration side effects

pytestmark = pytest.mark.model_onboarding

_BACKGROUND = (128, 0, 160)  # purple
_FOREGROUND = (255, 220, 0)  # yellow


def _declared_openrouter_models() -> list[str]:
    """Read models straight from OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT — never keep a copy here.

    Text-only models are exempt BY DECLARATION (flag False), not by
    omission: they route tool media through the caption fallback instead.
    """
    return [
        model_id
        for model_id, sees_tool_images in OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT.items()
        if sees_tool_images
    ]


def _models_under_test() -> list[str]:
    """Use declared models by default, or GAIA_ONBOARD_MODELS to vet a candidate before adding it to the constants."""
    override = os.environ.get("GAIA_ONBOARD_MODELS", "").strip()
    if override:
        return [name.strip() for name in override.split(",") if name.strip()]
    return _declared_openrouter_models()


def _two_colour_png() -> str:
    """Build a yellow square on purple — two colours the model must name to prove it saw it."""
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
    """The exact shape our agent produces: a read tool result carrying pixels, asserted on content not status."""
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
