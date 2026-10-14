"""Tolerate streaming chunks that omit finish_reason.

The OpenRouter SDK types ChatStreamChoice.finish_reason as REQUIRED, but
OpenAI-compatible gateways (observed: opencode zen, x-preview-f-free) omit it
on intermediate deltas — reasoning models stream chunks with no finish
reason until the last one, and pydantic raises "Field required", killing the
whole stream. OpenRouter's own wire format always carries it; this only
bites custom/base-URL lanes.

Give the field a None default so absent means "still streaming"; a present
value parses exactly as before. Drop once the SDK makes it optional
(openrouter 0.10.0 still requires it); fails loudly if the field is renamed.
"""

from openrouter.components.chatstreamchoice import ChatStreamChoice


def apply() -> None:
    field = ChatStreamChoice.model_fields.get("finish_reason")
    if field is None:
        raise AttributeError("ChatStreamChoice has no finish_reason field; patch is stale")
    field.default = None
    ChatStreamChoice.model_rebuild(force=True)
