"""The events stream's meters: every series at zero, the size edges a screen is judged by, and one connection's count."""

from collections.abc import AsyncGenerator

from prometheus_client import REGISTRY
from prometheus_client.utils import floatToGoString
import pytest

from app.constants.conversation import EventsWire
from app.services.conversation.stream_metrics import (
    OPENING_FRAME_BYTES,
    STREAM_BYTES_TOTAL,
    create_events_stream_series,
    metered,
)
from shared.py.analytics.catalog.attribution import EntrySurface
from tests.helpers import captured_wide_event, series_labels

pytestmark = pytest.mark.unit

_KEEPALIVE = ": keepalive\n\n"
_EVERY_SERIES = {(wire, surface.value) for wire in ("1", "2") for surface in EntrySurface}


def _value(sample: str, wire: EventsWire, surface: EntrySurface, **more: str) -> float:
    labels = {"wire": str(wire.value), "surface": surface.value, **more}
    return REGISTRY.get_sample_value(f"gaia_conversation_events_{sample}", labels) or 0.0


async def _lines(*lines: str, closed: list[bool] | None = None) -> AsyncGenerator[str]:
    try:
        for line in lines:
            yield line
    finally:
        if closed is not None:
            closed.append(True)


def test_every_wire_and_surface_has_its_series_before_the_first_stream() -> None:
    OPENING_FRAME_BYTES.clear()
    STREAM_BYTES_TOTAL.clear()

    create_events_stream_series()

    assert series_labels("gaia_conversation_events_stream_bytes_total") == _EVERY_SERIES
    assert series_labels("gaia_conversation_events_opening_frame_bytes_count") == _EVERY_SERIES
    assert _value("stream_bytes_total", EventsWire.PATCHES, EntrySurface.WEB) == 0


@pytest.mark.parametrize(
    "edge", [100 * 1024, 1024 * 1024, 5 * 1024 * 1024, 20 * 1024 * 1024], ids=str
)
async def test_an_opening_frame_lands_on_its_side_of_each_size_edge(edge: int) -> None:
    wire, surface, le = EventsWire.PATCHES, EntrySurface.DESKTOP, floatToGoString(edge)
    before = _value("opening_frame_bytes_bucket", wire, surface, le=le)
    opening = "data: " + "x" * (edge - len("data: \n\n")) + "\n\n"

    async with captured_wide_event():
        _ = [sent async for sent in metered(_lines(opening), wire, surface)]
        _ = [sent async for sent in metered(_lines(opening[:-2] + "x\n\n"), wire, surface)]

    assert _value("opening_frame_bytes_bucket", wire, surface, le=le) - before == 1


async def test_a_connection_s_frames_are_counted_without_its_keepalives() -> None:
    wire, surface = EventsWire.ITEMS, EntrySurface.VOICE
    lines = (_KEEPALIVE, "data: {}\n\n", _KEEPALIVE, "data: {é}\n\n")
    before = [
        _value(sample, wire, surface)
        for sample in ("stream_bytes_total", "opening_frame_bytes_sum", "opening_frame_bytes_count")
    ]

    async with captured_wide_event() as event:
        sent = [chunk async for chunk in metered(_lines(*lines), wire, surface)]
        stream = dict(event["conversation"])

    assert sent == [line.encode() for line in lines]
    assert stream == {"opening_frame_bytes": len(b"data: {}\n\n"), "frames": 2}
    assert [
        _value(sample, wire, surface) - was
        for sample, was in zip(
            ("stream_bytes_total", "opening_frame_bytes_sum", "opening_frame_bytes_count"),
            before,
            strict=True,
        )
    ] == [len("".join(lines).encode()), len(b"data: {}\n\n"), 1]


async def test_a_connection_dropped_mid_stream_counts_what_was_sent_and_closes_its_lines() -> None:
    wire, surface = EventsWire.PATCHES, EntrySurface.BOT
    closed: list[bool] = []
    before = _value("stream_bytes_total", wire, surface)

    async with captured_wide_event() as event:
        stream = metered(_lines("data: 1\n\n", "data: 2\n\n", closed=closed), wire, surface)
        first = await anext(stream)
        second = await anext(stream)
        await stream.aclose()
        frames = event["conversation"]["frames"]

    # The second frame was handed over and never asked past: its send is not known to have ended.
    assert (first, second, frames, closed) == (b"data: 1\n\n", b"data: 2\n\n", 1, [True])
    assert _value("stream_bytes_total", wire, surface) - before == len(first)


async def test_an_opening_frame_whose_send_never_ended_is_not_measured() -> None:
    wire, surface = EventsWire.PATCHES, EntrySurface.BOT
    before = _value("opening_frame_bytes_count", wire, surface)

    async with captured_wide_event() as event:
        stream = metered(_lines("data: 1\n\n"), wire, surface)
        await anext(stream)
        await stream.aclose()
        measured = dict(event["conversation"])

    assert measured == {"frames": 0}
    assert _value("opening_frame_bytes_count", wire, surface) == before
