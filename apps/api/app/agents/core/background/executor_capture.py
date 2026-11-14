"""The approval cards an executor run's session holds, which hil records there rather than on the work's card record."""

from collections.abc import Iterable, Iterator, Mapping

from app.agents.core.background.session import get_session
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.conversation_frame_models import ToolDataEvent
from app.services.conversation.graph_payloads import payloads_of_custom
from app.services.conversation.tool_cards import fold_cards
from shared.py.conversation_wire import ToolDataEntry


def session_approval_cards(stream_id: str) -> tuple[ToolDataEntry, ...]:
    """Return the run's approval cards, each in the latest state hil recorded for it."""
    session = get_session(stream_id)
    events = session.tool_events if session is not None else []
    return fold_cards(_approval_events(events)).tool_data


def _approval_events(events: Iterable[Mapping[str, object]]) -> Iterator[ToolDataEvent]:
    for event in events:
        for payload in payloads_of_custom(event):
            if isinstance(payload, ToolDataEvent):
                card: ToolDataEntry = payload.tool_data
                if card["tool_name"] == APPROVAL_REQUEST_TOOL_NAME:
                    yield payload
