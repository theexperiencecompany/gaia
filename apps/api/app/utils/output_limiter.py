"""Head + tail truncation for tool outputs that may be unbounded.

Used by the `bash` tool so a runaway command doesn't return MB of text into
the conversation. Keeps the start (where errors usually appear) and the end
(where final results appear) with a clearly-marked skip in the middle.
"""

from __future__ import annotations

DEFAULT_HEAD_BYTES = 16 * 1024  # 16 KB
DEFAULT_TAIL_BYTES = 4 * 1024  # 4 KB


def truncate_head_tail(
    text: str,
    head_bytes: int = DEFAULT_HEAD_BYTES,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> str:
    """Cap a string at `head_bytes + tail_bytes` with a skip indicator.

    Operates on UTF-8 byte length so the cap reflects what the LLM actually
    consumes. Returns the original string unchanged if it fits.
    """
    if head_bytes < 0 or tail_bytes < 0:
        raise ValueError("head_bytes and tail_bytes must be non-negative")

    encoded = text.encode("utf-8")
    total = len(encoded)
    if total <= head_bytes + tail_bytes:
        return text

    skipped = total - head_bytes - tail_bytes
    head = _safe_decode(encoded[:head_bytes])
    tail = _safe_decode(encoded[-tail_bytes:]) if tail_bytes else ""
    marker = f"\n\n... [{skipped} bytes truncated] ...\n\n"
    return f"{head}{marker}{tail}"


def _safe_decode(b: bytes) -> str:
    """Decode UTF-8 bytes, tolerating a split multibyte character at the edge."""
    return b.decode("utf-8", errors="replace")
