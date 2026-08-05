"""Parse a chat stream into typed frames a test can assert on.

The chat SSE vocabulary has no ``type`` discriminator — the single top-level
JSON key of each ``data:`` line *is* the discriminator (see
``app/models/stream_events.py``). The one exception is the identity frame,
which carries several keys at once; it is recognised by its id fields.

Tool visibility is the reason this module exists. A tool call reaches the
client as a ``tool_data`` frame whose ``tool_name`` is always the literal
``"tool_calls_data"``; the tool the model actually called is nested at
``data.tool_name`` and its arguments at ``data.inputs``. The result arrives
later as a separate ``tool_output`` frame joined only by ``tool_call_id`` —
exactly the join the frontend performs in
``libs/shared/ts/src/chat/streaming.ts`` (``mergeToolOutputIntoToolData``).
``Transcript`` performs that same join so a test can assert a tool's arguments
and its result together, and so a broken join fails here rather than silently
rendering a tool card that never fills in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from typing import Any

DATA_PREFIX = "data: "
NOSTREAM_PREFIX = "nostream: "
ID_PREFIX = "id: "
DONE_SENTINEL = "[DONE]"

#: Every tool call rides a frame whose outer ``tool_name`` is this literal.
TOOL_CALLS_DATA = "tool_calls_data"

#: Synthetic kinds for the frames that are not a single-key JSON object.
DONE = "done"
INIT = "conversation_initialized"
#: A multi-key frame carrying no key the vocabulary recognises. Real: a tool
#: whose native-card field is absent from ``tool_fields`` is passed through by
#: ``normalize_custom_event`` untouched, siblings and all (``fetch_webpages``
#: emits ``{"webpage_data": ..., "fetched_urls": [...]}``). The client does not
#: reject those either — ``streaming.ts`` logs and yields ``{type:"unknown"}``,
#: absorbing the payload into ``extras`` — so neither does this parser.
UNKNOWN = "unknown"

_INIT_KEYS = frozenset({"user_message_id", "bot_message_id", "stream_id"})


class TranscriptError(AssertionError):
    """The stream is not parseable as the documented SSE vocabulary."""


@dataclass(frozen=True)
class Frame:
    """One ``data:`` line, discriminated by its single top-level key."""

    kind: str
    data: Any
    payload: dict[str, Any]
    event_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """A tool call as the client sees it, unwrapped from its nested envelope."""

    name: str
    args: dict[str, Any]
    tool_call_id: str | None
    category: str
    message: str | None
    show_category: bool
    subagent_id: str | None
    index: int
    entry: dict[str, Any]


@dataclass(frozen=True)
class ToolOutput:
    tool_call_id: str
    output: str
    subagent_id: str | None
    index: int


def _split_frame(block: str) -> tuple[str | None, str]:
    """Split an optional ``id:`` line off a frame, returning (id, body)."""
    if not block.startswith(ID_PREFIX):
        return None, block
    id_line, _, rest = block.partition("\n")
    return id_line[len(ID_PREFIX) :], rest


def _classify(payload: dict[str, Any]) -> str:
    if len(payload) == 1:
        return next(iter(payload))
    if payload.keys() >= _INIT_KEYS:
        return INIT
    # A native card can carry sibling keys: ``normalize_custom_event`` wraps the
    # recognised tool field into ``tool_data`` and deliberately preserves the
    # rest of the tool's payload beside it (``nextPageToken`` next to
    # ``email_fetch_data``). The envelope is still the discriminator.
    if "tool_data" in payload:
        return "tool_data"
    return UNKNOWN


class Transcript:
    """A parsed chat stream, queried by frame kind and by tool.

    Build it with :meth:`from_chunks` (the strings ``execute_graph_streaming``
    yields) or :meth:`from_sse` (a raw HTTP response body).
    """

    def __init__(
        self,
        frames: list[Frame],
        nostream: list[dict[str, Any]],
        blocks: list[str],
    ) -> None:
        self._frames = frames
        self._nostream = nostream
        self._blocks = blocks

    # -- construction -------------------------------------------------------

    @classmethod
    def from_chunks(cls, chunks: Iterable[str]) -> Transcript:
        """Parse the chunk strings yielded by ``execute_graph_streaming``.

        Each yield is exactly one frame, so chunks are parsed individually —
        joining them first would glue the ``nostream:`` marker (which has no
        blank-line terminator) onto the frame that follows it.
        """
        return cls._build(list(chunks))

    @classmethod
    def from_events(cls, payloads: Iterable[dict[str, Any]]) -> Transcript:
        """Parse the dicts handed to a ``stream_writer``.

        Subagents and the background executor do not yield SSE — they call a
        writer, which serializes each dict as ``data: {json}\\n\\n`` verbatim
        (``background/redis_writer.py``). So a writer payload *is* a frame, and
        the same assertions apply on both sides of that boundary.
        """
        return cls._build([f"{DATA_PREFIX}{json.dumps(p)}\n\n" for p in payloads])

    @classmethod
    def from_sse(cls, body: str) -> Transcript:
        """Parse a raw SSE response body (frames separated by a blank line)."""
        return cls._build([f"{block}\n\n" for block in body.split("\n\n") if block])

    @classmethod
    def _build(cls, blocks: list[str]) -> Transcript:
        frames: list[Frame] = []
        nostream: list[dict[str, Any]] = []
        for block in blocks:
            if not block.strip():
                continue
            if block.startswith(NOSTREAM_PREFIX):
                nostream.append(json.loads(block[len(NOSTREAM_PREFIX) :]))
                continue
            event_id, body = _split_frame(block)
            if not body.startswith(DATA_PREFIX):
                raise TranscriptError(f"frame is not an SSE data line: {block!r}")
            if not body.endswith("\n\n"):
                raise TranscriptError(
                    f"SSE frame is not terminated by a blank line, so a client would "
                    f"fold it into the next event: {block!r}"
                )
            raw = body[len(DATA_PREFIX) : -2]
            if raw == DONE_SENTINEL:
                frames.append(Frame(kind=DONE, data=None, payload={}, event_id=event_id))
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise TranscriptError(f"frame payload is not a JSON object: {raw!r}")
            kind = _classify(payload)
            # An unrecognised frame has no field to unwrap, so its ``data`` is
            # the whole payload — the same thing the client keeps in ``extras``.
            data = payload if kind == UNKNOWN else payload.get(kind)
            frames.append(Frame(kind=kind, data=data, payload=payload, event_id=event_id))
        return cls(frames, nostream, blocks)

    # -- frame-level queries ------------------------------------------------

    def frames(self) -> list[Frame]:
        return list(self._frames)

    def kinds(self) -> list[str]:
        """Ordered frame kinds — the wire-level shape of the turn."""
        return [f.kind for f in self._frames]

    def of_kind(self, kind: str) -> list[Any]:
        """The ``data`` values of every frame with this top-level key."""
        return [f.data for f in self._frames if f.kind == kind]

    def raw(self) -> list[str]:
        """The unparsed chunks, for asserting on the bytes themselves."""
        return list(self._blocks)

    @property
    def is_done(self) -> bool:
        return any(f.kind == DONE for f in self._frames)

    # -- tool visibility ----------------------------------------------------

    def tool_calls(self) -> list[ToolCall]:
        """Every tool call visible in the stream, in emission order.

        Unwraps the ``tool_calls_data`` envelope: ``data.tool_name`` is the tool
        the model called, ``tool_name`` on the entry itself is always the
        literal envelope marker. Non-tool-call ``tool_data`` variants
        (``mcp_app``, ``todo_progress``, ``approval_request``) are skipped.
        """
        calls: list[ToolCall] = []
        for index, frame in enumerate(self._frames):
            if frame.kind != "tool_data":
                continue
            entries = frame.data if isinstance(frame.data, list) else [frame.data]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("tool_name") != TOOL_CALLS_DATA:
                    continue
                inner = entry.get("data")
                if not isinstance(inner, dict):
                    raise TranscriptError(f"tool_calls_data entry has no data object: {entry!r}")
                calls.append(
                    ToolCall(
                        name=inner.get("tool_name", ""),
                        args=inner.get("inputs", {}),
                        tool_call_id=inner.get("tool_call_id"),
                        category=entry.get("tool_category", ""),
                        message=inner.get("message"),
                        show_category=bool(inner.get("show_category")),
                        subagent_id=entry.get("subagent_id"),
                        index=index,
                        entry=entry,
                    )
                )
        return calls

    def tool_names(self) -> list[str]:
        """The real tool names, in the order the client sees them."""
        return [c.name for c in self.tool_calls()]

    def tool_call(self, name: str) -> ToolCall:
        """The single call to ``name``; fails loud on zero or several."""
        matches = [c for c in self.tool_calls() if c.name == name]
        if len(matches) != 1:
            raise TranscriptError(
                f"expected exactly one {name!r} tool call, got {len(matches)} "
                f"(stream had: {self.tool_names()})"
            )
        return matches[0]

    def args(self, name: str) -> dict[str, Any]:
        return self.tool_call(name).args

    def outputs(self) -> list[ToolOutput]:
        return [
            ToolOutput(
                tool_call_id=frame.data["tool_call_id"],
                output=frame.data["output"],
                subagent_id=frame.data.get("subagent_id"),
                index=index,
            )
            for index, frame in enumerate(self._frames)
            if frame.kind == "tool_output"
        ]

    def result_for(self, name: str) -> str | None:
        """The result text for ``name``, joined to its call by ``tool_call_id``.

        ``None`` when no output frame carries that id — the same condition that
        leaves the frontend's tool card stuck without a result.
        """
        call = self.tool_call(name)
        if call.tool_call_id is None:
            return None
        for output in self.outputs():
            if output.tool_call_id == call.tool_call_id:
                return output.output
        return None

    # -- text ---------------------------------------------------------------

    def final_text(self) -> str:
        """The assistant reply as assembled from the ``response`` deltas."""
        return "".join(self.of_kind("response"))

    def reasoning_text(self) -> str:
        return "".join(payload.get("content", "") for payload in self.of_kind("reasoning"))

    def subagent_ids(self) -> list[str]:
        return [payload["subagent_id"] for payload in self.of_kind("subagent_start")]

    # -- internal control markers (never reach the client) ------------------

    def nostream(self) -> list[dict[str, Any]]:
        """The ``nostream:`` markers, consumed by the chat service before the wire."""
        return list(self._nostream)

    def complete_message(self) -> str:
        """The persisted bot text carried by the completion marker."""
        if len(self._nostream) != 1:
            raise TranscriptError(
                f"expected exactly one nostream marker, got {len(self._nostream)}"
            )
        return self._nostream[0]["complete_message"]

    @property
    def cancelled(self) -> bool:
        return any(marker.get("cancelled") for marker in self._nostream)
