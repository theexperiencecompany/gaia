"""A run that reaches an action the user asked to approve first, scripted the way a real model reads its prompt."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

from bson import ObjectId
from langchain_core.messages import BaseMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import PrivateAttr

from app.models.hil_models import HILPreferences
from tests.conftest import FAKE_USER
from tests.e2e._harness.graph_run import StreamingScriptedModel, call, streaming_model

#: Pure and outside the executor's initial tools: reaching it runs the real
#: retrieve -> bind -> call hop, and its card is the tool's own real output.
FLOWCHART = {"description": "the deploy's three checks", "direction": "LR"}
READ_APPROVAL_ID = "<the approval id in the prompt>"
APPROVAL_READY = re.compile(r"APPROVAL_READY (\S+):")
WAITING = "Waiting on your approval to draw the deploy's flowchart."
DRAWN = "Drew the deploy's flowchart."
SKIPPED = "Skipped the flowchart, as you declined it."


@dataclass
class Hold:
    """Model calls held open: reached once one is waiting, and let go together on release."""

    reached: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)


class PromptReadingModel(StreamingScriptedModel):
    """A scripted model that reads its prompt as a real one does: for an approval id, and to wait.

    A redeem scripted with READ_APPROVAL_ID carries the id the ticket names; a
    call whose prompt holds a held phrase waits for the test, the way a slow
    model call keeps a run, and the chat's executor lock, held.
    """

    _holds: dict[str, Hold] = PrivateAttr(default_factory=dict)

    def hold_calls_seeing(self, phrase: str) -> Hold:
        self._holds[phrase] = Hold()
        return self._holds[phrase]

    async def _astream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        prompt = _prompt_text(messages)
        for phrase, hold in self._holds.items():
            if phrase in prompt:
                hold.reached.set()
                await hold.released.wait()
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        result = super()._generate(messages, *args, **kwargs)
        for tool_call in result.generations[0].message.tool_calls:
            data = tool_call["args"].get("data")
            if isinstance(data, dict) and data.get("id") == READ_APPROVAL_ID:
                ticket = APPROVAL_READY.search(_prompt_text(messages))
                assert ticket, "a redeem was scripted, but no APPROVAL_READY reached the model"
                data["id"] = ticket.group(1)
        return result


def _prompt_text(messages: list[BaseMessage]) -> str:
    return " ".join(str(m.content) for m in messages)


def gated_run(after_the_verdict: Sequence[Any]) -> PromptReadingModel:
    """Script a run that proposes the gated flowchart and says it waits, then what follows the verdict."""
    script = [
        call("retrieve_tools", {"exact_tool_names": ["create_flowchart"]}, call_id="tc_find"),
        call("create_flowchart", FLOWCHART, call_id="tc_flow"),
        WAITING,
        *after_the_verdict,
    ]
    return PromptReadingModel(responses=streaming_model(script).responses)


def redeem() -> Any:
    return call(
        "execute",
        {
            "task_description": "draw the approved flowchart",
            "tool_name": "approve",
            "data": {"id": READ_APPROVAL_ID},
        },
        call_id="tc_redeem",
    )


async def ask_before(mongo_db: AsyncIOMotorDatabase, tool_name: str) -> None:
    """Set the owner to be asked before every call of the tool, as their HIL settings would."""
    await mongo_db["users"].update_one(
        {"_id": ObjectId(FAKE_USER.user_id)},
        {
            "$set": {
                "hil_preferences": HILPreferences(
                    mode="always_ask", tool_overrides={tool_name: True}
                ).model_dump()
            }
        },
    )
