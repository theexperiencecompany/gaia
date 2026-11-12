"""Turn one comms run's raw graph stream events into the events the conversation step consumes.

The visible frames come from the same translator the chat stream uses
(frames_for_stream_event); this module only decodes those frames into typed
payloads and adds what the step needs beside them: when the model node
returned, when the silent summarization call ran, and how the run ended.
"""

from collections.abc import Mapping
import json
from typing import cast

from pydantic import TypeAdapter

from app.agents.core.comms_directive import interpret_comms_output
from app.agents.core.held_replies import last_ai_message
from app.constants.comms import CommsDirectiveKind
from app.constants.streaming import SSE_DATA_PREFIX
from app.helpers.agent_helpers import (
    StreamAccumulators,
    flush_held_frames,
    frames_for_stream_event,
)
from app.models.agent_models import StreamChunkMetadata
from app.models.conversation_frame_models import (
    FollowUpActionsEvent,
    StreamPayload,
    StreamPayloadType,
    ToolDataEvent,
)
from app.models.tool_data_models import ToolDataEntry
from app.services.conversation.ports import (
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    RunEvent,
    RunOutcome,
    Silent,
    Streamed,
    Summarized,
)
from app.utils.agent_utils import NodeMessagesUpdate
from app.utils.multimodal import extract_text_content

#: The comms graph node that runs the model.
_MODEL_NODE = "agent"
_PAYLOADS: TypeAdapter[StreamPayload] = TypeAdapter(StreamPayload)
_PAYLOAD_KEYS = frozenset(StreamPayloadType)
GraphEvent = tuple[tuple[str, ...], str, object]


def payload_from_frame(frame: str) -> StreamPayload | None:
    """Decode one chat stream frame into its typed payload, or None for a frame the conversation stream does not carry."""
    if not frame.startswith(SSE_DATA_PREFIX):
        return None
    data = json.loads(frame.removeprefix(SSE_DATA_PREFIX))
    if not isinstance(data, dict):
        return None
    key = next((key for key in data if key in _PAYLOAD_KEYS), None)
    if key is None:
        return None
    return _PAYLOADS.validate_python({"type": key, key: data[key]})


class CommsEventMapper:
    """The per-run state of the translation: held text, cards shown, and the model's last answer."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id
        self._frames = StreamAccumulators()
        self._summarized = False
        self._answered = False
        self._cards: list[ToolDataEntry] = []
        self._follow_ups: tuple[str, ...] = ()
        self._answer = ""

    async def map(self, event: GraphEvent) -> list[RunEvent]:
        """Return the step events one graph stream event produces, in the order the step must see them."""
        namespace, mode, payload = event
        top_level = not namespace
        out: list[RunEvent] = []
        if top_level and mode == "messages" and self._is_summary_call(payload):
            self._summarized = True
            out.append(Summarized())
        async for frame in frames_for_stream_event(event, self._frames, True, None, self._user_id):
            out.extend(self._streamed(frame))
        if top_level and mode == "updates":
            out.extend(self._model_output(payload))
        return out

    def finish(self) -> list[RunEvent]:
        """Return the frames still owed once the stream ended, then the run's outcome."""
        tail = [
            event for frame in flush_held_frames(self._frames) for event in self._streamed(frame)
        ]
        return [*tail, Finished(outcome=self._outcome())]

    def _is_summary_call(self, payload: object) -> bool:
        """Return True for the summarization pass: a silent model call before the final answer, not follow-up work after it."""
        if self._summarized or self._answered:
            return False
        # LangGraph's messages mode yields (chunk, metadata) pairs (Type Safety item 12).
        metadata: StreamChunkMetadata
        _chunk, metadata = cast(tuple[object, StreamChunkMetadata], payload)
        return bool(metadata.get("silent"))

    def _streamed(self, frame: str) -> list[RunEvent]:
        payload = payload_from_frame(frame)
        if payload is None:
            return []
        if isinstance(payload, ToolDataEvent):
            self._cards.append(payload.tool_data)
        elif isinstance(payload, FollowUpActionsEvent):
            self._follow_ups = tuple(payload.follow_up_actions)
        return [Streamed(payload=payload)]

    def _model_output(self, payload: object) -> list[RunEvent]:
        if not isinstance(payload, Mapping) or _MODEL_NODE not in payload:
            return []
        update = payload[_MODEL_NODE]
        if not isinstance(update, Mapping):
            return []
        answer = last_ai_message(NodeMessagesUpdate.model_validate(update).messages)
        if answer is None:
            return []
        has_tool_calls = bool(answer.tool_calls)
        if not has_tool_calls:
            self._answered = True
            self._answer = extract_text_content(answer.content)
        return [ModelOutput(has_tool_calls=has_tool_calls)]

    def _outcome(self) -> RunOutcome:
        directive = interpret_comms_output(self._answer)
        match directive.kind:
            case CommsDirectiveKind.REACT if not self._cards:
                return Reacted(emoji=directive.payload)
            case CommsDirectiveKind.REPLY:
                text = directive.payload
            case _:
                text = ""
        if not text and not self._cards:
            return Silent()
        return Replied(text=text, tool_data=tuple(self._cards), follow_up_actions=self._follow_ups)
