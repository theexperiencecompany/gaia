"""Vision support: one canonical media shape in history, per-lane delivery at
the request boundary, and a text description for models that can't see at all.

- `capability` — what the active (provider, model) lane can receive.
- `adapter` — rewrites a request's messages to fit that lane, within budget.
- `describe` — the fallback that turns an image into prose.
"""

from app.agents.llm.vision.adapter import MediaAdapter, adapt_media_for_model
from app.agents.llm.vision.capability import (
    VisionCapability,
    active_lane,
    model_can_view_images,
    resolve_vision_capability,
)
from app.agents.llm.vision.describe import describe_image

__all__ = [
    "MediaAdapter",
    "VisionCapability",
    "active_lane",
    "adapt_media_for_model",
    "describe_image",
    "model_can_view_images",
    "resolve_vision_capability",
]
