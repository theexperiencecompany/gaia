"""Turn one comms run's raw graph stream events into the events the conversation step consumes.

The visible payloads come from the one graph translator (payloads_for_stream_event); this
module adds what the step needs beside them: when the model node returned, when the silent
summarization call ran, and how the run ended.
"""

from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError

from app.agents.core.comms_directive import interpret_comms_output
from app.agents.core.held_replies import last_ai_message
from app.constants.comms import CommsDirectiveKind
from app.models.agent_models import StreamChunkMetadata
from app.models.conversation_frame_models import (
    FollowUpActionsEvent,
    StreamPayload,
    ToolDataEvent,
)
from app.models.stream_events import MainResponseCompleteFrame
from app.services.conversation.graph_payloads import (
    GraphStreamState,
    flush_held_payloads,
    payloads_for_stream_event,
)
from app.services.conversation.ports import (
    Answered,
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    RunEvent,
    RunOutcome,
    Silent,
    Streamed,
    Summarized,
    ToolsRan,
)
from app.utils.agent_utils import NodeMessagesUpdate
from app.utils.multimodal import extract_text_content
from shared.py.conversation_wire import ToolDataEntry

#: The comms graph node that runs the model.
_MODEL_NODE = "agent"
#: The comms graph node that runs the model's tool calls.
_TOOLS_NODE = "tools"
GraphEvent = tuple[tuple[str, ...], str, object]


def _marks_answer_complete(payload: object) -> bool:
    """Return whether a custom event is the follow-up pass announcing the main answer is complete."""
    try:
        return MainResponseCompleteFrame.model_validate(payload).main_response_complete
    except ValidationError:
        return False


class CommsEventMapper:
    """The per-run state of the translation: held text, cards shown, and the model's last answer."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id
        self._graph = GraphStreamState()
        self._summarized = False
        self._answered = False
        self._cards: list[ToolDataEntry] = []
        self._follow_ups: tuple[str, ...] = ()
        self._answer = ""
        self._final_reported = False

    async def map(self, event: GraphEvent) -> list[RunEvent]:
        """Return the step events one graph stream event produces, in the order the step must see them."""
        namespace, mode, payload = event
        top_level = not namespace
        out: list[RunEvent] = []
        if top_level and mode == "messages" and self._is_summary_call(payload):
            self._summarized = True
            out.append(Summarized())
        async for streamed in payloads_for_stream_event(
            event, self._graph, True, None, self._user_id
        ):
            out.append(self._streamed(streamed))
        if top_level and mode == "updates":
            out.extend(self._model_output(payload))
            if isinstance(payload, Mapping) and _TOOLS_NODE in payload:
                out.append(ToolsRan())
        if top_level and mode == "custom" and _marks_answer_complete(payload):
            out.extend(self._answer_final())
        return out

    def _answer_final(self) -> list[RunEvent]:
        """Return the held tail and the answer as final: what follows is only follow-up suggestions."""
        if self._final_reported:
            return []
        self._final_reported = True
        tail = [self._streamed(payload) for payload in flush_held_payloads(self._graph)]
        return [*tail, Answered(outcome=self._outcome())]

    def finish(self) -> list[RunEvent]:
        """Return the frames still owed once the stream ended, then the run's outcome."""
        tail = [self._streamed(payload) for payload in flush_held_payloads(self._graph)]
        return [*tail, Finished(outcome=self._outcome())]

    def _is_summary_call(self, payload: object) -> bool:
        """Return True for the summarization pass: a silent model call before the final answer, not follow-up work after it."""
        if self._summarized or self._answered:
            return False
        # LangGraph's messages mode yields (chunk, metadata) pairs (Type Safety item 12).
        metadata: StreamChunkMetadata
        _chunk, metadata = cast(tuple[object, StreamChunkMetadata], payload)
        return bool(metadata.get("silent"))

    def _streamed(self, payload: StreamPayload) -> RunEvent:
        if isinstance(payload, ToolDataEvent):
            self._cards.append(payload.tool_data)
        elif isinstance(payload, FollowUpActionsEvent):
            self._follow_ups = tuple(payload.follow_up_actions)
        return Streamed(payload=payload)

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
