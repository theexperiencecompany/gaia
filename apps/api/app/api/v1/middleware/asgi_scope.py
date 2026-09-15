"""The raw ASGI scope/message fields the pure-ASGI middlewares read.

Parsed once at the middleware boundary so the rest of each middleware reads
attributes, not string keys off Starlette's scope mapping.
"""

from pydantic import BaseModel, ConfigDict


class AsgiScope(BaseModel):
    """An ASGI connection scope — ``type``, ``path`` and the raw header pairs."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    path: str = ""
    headers: list[tuple[bytes, bytes]] = []

    def header(self, key: bytes) -> str | None:
        """Return the value of a header (lower-case name), if present."""
        for name, value in self.headers:
            if name == key:
                return value.decode("latin-1")  # pragma: no mutate -- case-insensitive codec
        return None


class AsgiMessage(BaseModel):
    """An ASGI send/receive event — only its ``type`` is ever inspected."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
