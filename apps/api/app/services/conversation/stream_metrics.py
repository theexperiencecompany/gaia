"""Measure what the events stream sends one connection: its opening frame and every byte after.

Labelled by the wire the client asked for and the surface it came from, never by a
conversation or a user; a connection's own numbers go on its request's wide event.
Every series is created at zero when the API starts, so a surface's first stream is an increase.
"""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Final

from prometheus_client import Counter, Histogram

from app.constants.conversation import EventsWire
from app.utils.prometheus_registry import register_once
from shared.py.analytics.catalog.attribution import EntrySurface
from shared.py.wide_events import log

_KB: Final = 1024
_MB: Final = 1024 * _KB

#: Edges at the sizes a screen is judged by: 100 KB, 1 MB, 5 MB and 20 MB.
_OPENING_FRAME_BUCKETS: Final[tuple[float, ...]] = (
    _KB,
    10 * _KB,
    100 * _KB,
    500 * _KB,
    _MB,
    2 * _MB,
    5 * _MB,
    10 * _MB,
    20 * _MB,
)

#: How an SSE line that carries a frame starts; a keepalive is a comment.
_FRAME_LINE: Final = "data: "

_LABELS: Final = ("wire", "surface")

OPENING_FRAME_BYTES = register_once(
    "gaia_conversation_events_opening_frame_bytes",
    lambda: Histogram(
        name="gaia_conversation_events_opening_frame_bytes",
        documentation="Bytes of the screen frame an events stream opens on, by wire and surface",
        labelnames=_LABELS,
        buckets=_OPENING_FRAME_BUCKETS,
    ),
)

STREAM_BYTES_TOTAL = register_once(
    "gaia_conversation_events_stream_bytes_total",
    lambda: Counter(
        name="gaia_conversation_events_stream_bytes_total",
        documentation="Bytes the events stream sent its clients, by wire and surface",
        labelnames=_LABELS,
    ),
)


def create_events_stream_series() -> None:
    """Create every wire and surface's series at zero, so its first stream is visible."""
    for wire in EventsWire:
        for surface in EntrySurface:
            OPENING_FRAME_BYTES.labels(str(wire.value), surface.value)
            STREAM_BYTES_TOTAL.labels(str(wire.value), surface.value)


async def metered(
    lines: AsyncGenerator[str], wire: EventsWire, surface: EntrySurface
) -> AsyncGenerator[bytes]:
    """Yield a stream's SSE lines as the bytes sent, counting them and the frame it opens on.

    The request's wide event gets the opening frame's bytes when it is sent, and the
    frames written when the stream closes.
    """
    labels = (str(wire.value), surface.value)
    frames = 0
    try:
        async with aclosing(lines):
            async for line in lines:
                sent = line.encode()
                if line.startswith(_FRAME_LINE):
                    if not frames:
                        OPENING_FRAME_BYTES.labels(*labels).observe(len(sent))
                        log.set_ns("conversation", opening_frame_bytes=len(sent))
                    frames += 1
                yield sent
                STREAM_BYTES_TOTAL.labels(*labels).inc(len(sent))
    finally:
        log.set_ns("conversation", frames=frames)
