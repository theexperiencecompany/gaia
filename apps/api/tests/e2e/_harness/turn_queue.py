"""A scripted model fed turn by turn while the graphs that hold it stay open."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from tests.e2e._harness.graph_run import StreamingScriptedModel

#: Stands in, in a queued call's args, for the approval id the run's prompt names.
APPROVAL_ID_FROM_PROMPT = "<approval id from the prompt>"
_APPROVAL_READY = re.compile(r"APPROVAL_READY (\S+):")
#: Stands in, in a queued call_executor, for the handle of the newest message the prompt shows.
MESSAGE_FROM_PROMPT = -1
_MESSAGE_HANDLE = re.compile(r"\[#(\d+)\]")


class TurnQueue(StreamingScriptedModel):
    """Answer each model call with the next queued turn; a call nothing was queued for fails loudly."""

    _turns: deque[Any] = PrivateAttr(default_factory=deque)
    #: The tail of each prompt a call came with when nothing was queued; product code may swallow the raise.
    _unscripted: list[str] = PrivateAttr(default_factory=list)
    _down: bool = PrivateAttr(default=False)

    def then(self, turns: Iterable[Any]) -> None:
        self._turns.extend(turns)

    @property
    def pending(self) -> int:
        return len(self._turns)

    @property
    def queued(self) -> list[Any]:
        return list(self._turns)

    @property
    def unscripted(self) -> list[str]:
        return list(self._unscripted)

    @contextmanager
    def provider_down(self) -> Iterator[None]:
        """Fail every call inside the block the way a model provider outage does."""
        self._down = True
        try:
            yield
        finally:
            self._down = False

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self._prompts.append(list(messages))
        if self._down:
            raise RuntimeError("the model provider is down")
        if not self._turns:
            prompt = " ".join(str(m.content) for m in messages)[-600:]
            self._unscripted.append(prompt)
            raise AssertionError(
                f"the model was called with no turn queued; it was shown: {prompt}"
            )
        turn = self._turns.popleft()
        return ChatResult(generations=[ChatGeneration(message=_message(turn, messages))])


def _message(turn: Any, messages: list[BaseMessage]) -> BaseMessage:
    if isinstance(turn, BaseMessage):
        return turn
    if isinstance(turn, dict):
        return AIMessage(content="", tool_calls=[_with_prompt_ids(turn, messages)])
    if isinstance(turn, list):
        return AIMessage(content="", tool_calls=[_with_prompt_ids(c, messages) for c in turn])
    return AIMessage(content=str(turn))


def _with_prompt_ids(tool_call: dict[str, Any], messages: list[BaseMessage]) -> dict[str, Any]:
    """Fill an id placeholder from the prompt, as a model reads the id it was handed."""
    if tool_call["args"].get("for_messages") == [MESSAGE_FROM_PROMPT]:
        handles = _MESSAGE_HANDLE.findall(" ".join(str(m.content) for m in messages))
        assert handles, (
            "a hand-off was queued for the newest message, but no [#n] reached the model"
        )
        return {**tool_call, "args": {**tool_call["args"], "for_messages": [int(handles[-1])]}}
    data = tool_call["args"].get("data")
    if not (isinstance(data, dict) and data.get("id") == APPROVAL_ID_FROM_PROMPT):
        return tool_call
    found = _APPROVAL_READY.search(" ".join(str(m.content) for m in messages))
    assert found, "an approval redeem was queued, but no APPROVAL_READY reached the model"
    return {**tool_call, "args": {**tool_call["args"], "data": {**data, "id": found.group(1)}}}
