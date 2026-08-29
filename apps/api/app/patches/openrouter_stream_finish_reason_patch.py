"""Tolerate streaming chunks that omit ``finish_reason``.

The OpenRouter SDK types ``ChatStreamChoice.finish_reason`` as REQUIRED, but
OpenAI-compatible gateways legitimately omit it on intermediate deltas —
reasoning models in particular stream ``{"delta": {...}, "index": 0}`` with no
finish reason until the last chunk. One such chunk kills the whole stream:

    1 validation error for Unmarshaller
    body.data.choices.0.finish_reason
      Field required

Observed against the opencode zen gateway (`x-preview-f-free`). OpenRouter's
own wire format always carries the field, so this only bites custom/base-URL
lanes. Give the field a ``None`` default so absent means "still streaming";
a present value parses exactly as before.

Drop once the SDK makes ``finish_reason`` optional (openrouter 0.10.0 still
requires it); the import fails loudly if the field is renamed.
"""

from openrouter.components.chatstreamchoice import ChatStreamChoice


def apply() -> None:
    field = ChatStreamChoice.model_fields.get("finish_reason")
    if field is None:
        raise AttributeError("ChatStreamChoice has no finish_reason field; patch is stale")
    field.default = None
    ChatStreamChoice.model_rebuild(force=True)
