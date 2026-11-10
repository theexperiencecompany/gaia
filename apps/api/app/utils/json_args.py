"""Read a tool argument the model JSON-encoded as the value it encodes."""

import json


def decode_json_container(value: object) -> object:
    """Return the object or list a JSON text encodes; anything else is returned unchanged.

    Models often send an object or list argument as its JSON text. Used as a
    BeforeValidator, the arg's own type check still refuses anything else.
    """
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(decoded, dict | list):
            return decoded
    return value
