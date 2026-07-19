"""Vision support: one canonical media shape in history, per-lane delivery at
the request boundary, and a text description for models that can't see at all.

- `capability` — what the active (provider, model) lane can receive.
- `adapter` — rewrites a request's messages to fit that lane, within budget.
- `describe` — the fallback that turns an image into prose.
- `tool_media` — applies that fallback to a tool result, once, at execution time.
"""

from app.agents.llm.vision.adapter import MediaAdapter, adapt_media_for_model
from app.agents.llm.vision.capability import (
    MediaDelivery,
    active_lane,
    model_can_view_images,
    resolve_media_delivery,
)
from app.agents.llm.vision.describe import describe_image
from app.agents.llm.vision.tool_media import describe_tool_media

__all__ = [
    "MediaAdapter",
    "MediaDelivery",
    "active_lane",
    "adapt_media_for_model",
    "describe_image",
    "describe_tool_media",
    "model_can_view_images",
    "resolve_media_delivery",
]
