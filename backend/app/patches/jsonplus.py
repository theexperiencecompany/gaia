"""
Patch jsonplus to handle message serialization correctly.

This ensures that messages (like HumanMessage, AIMessage, etc.) are converted to a serializable format
when using msgpack encoding, preventing serialization errors.
"""

from typing import Any

import ormsgpack
from langgraph.checkpoint.serde import jsonplus
from langgraph.checkpoint.serde.jsonplus import _msgpack_default, _option


def message_to_dict(msg):
    """
    Recursively convert a message or object into a dict/str (safe for serialization).
    """
    # Handles HumanMessage, AIMessage, ToolMessage, etc.
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    elif isinstance(msg, dict):
        # Recursively convert dict values
        return {k: message_to_dict(v) for k, v in msg.items()}
    elif isinstance(msg, (list, tuple)):
        # Recursively convert each item
        return [message_to_dict(x) for x in msg]
    elif isinstance(msg, (str, int, float, bool, type(None))):
        return msg
    else:
        # Fallback: try to extract content and role
        return {
            "role": getattr(msg, "role", "user"),
            "content": str(getattr(msg, "content", msg)),
        }


def _msgpack_enc(data: Any) -> bytes:
    return ormsgpack.packb(
        message_to_dict(data), default=_msgpack_default, option=_option
    )


setattr(jsonplus, "_msgpack_enc", _msgpack_enc)
