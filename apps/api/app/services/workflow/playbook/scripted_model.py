"""The model that drives a playbook replay: it emits recorded calls and never thinks.

A replay runs inside a real agent graph so the pregel loop supplies the runtime,
the stream writer, the metadata copy, the middleware chain and the tool-call
plumbing — the same things it supplies an agentic run. What the graph must NOT
have is a model that reasons, so this stands in its place: turn ``N`` emits
``script[N]`` verbatim, and the turn after the last one emits a message with no
tool calls, which is how the agent loop ends.

The turn is counted off the messages the model is handed rather than held in a
cursor. LangGraph replays a superstep whenever a task retries, so a cursor would
step twice for one turn and desynchronise the script from the run.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

#: What the loop-ending turn says. Never read by anything — a replay's
#: user-facing text is written by the run's end-of-run model call — but an empty
#: assistant message is rewritten to "Empty response from model." by
#: ``create_agent``, which reads as a fault in a log.
REPLAY_FINISHED_CONTENT = "Playbook replay finished."


@dataclass(frozen=True, slots=True)
class ScriptedCall:
    """One recorded tool call: the tool, and the arguments it was recorded with."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


def scripted_call_id(turn: int) -> str:
    """The tool_call_id turn ``turn`` emits — derived, so a replayed turn reuses it."""
    return f"pb_call_{turn}"


class ScriptedModel(BaseChatModel):
    """Replays ``script`` one call per turn, consuming no tokens and no network."""

    script: list[ScriptedCall]

    @property
    def _llm_type(self) -> str:
        return "playbook-scripted"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,  # noqa: ANN401 -- BaseChatModel.bind_tools contract
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Hand back the model itself: a scripted turn does not depend on the tools.

        Overridden because ``BaseChatModel.bind_tools`` raises, and ``create_agent``
        binds the run's tools before every call.
        """
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,  # noqa: ANN401 -- BaseChatModel._generate contract
    ) -> ChatResult:
        del stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=self.turn_for(messages))])

    def turn_for(self, messages: Sequence[BaseMessage]) -> AIMessage:
        """The message this turn emits, derived entirely from ``messages``."""
        turn = sum(1 for message in messages if isinstance(message, AIMessage))
        if turn >= len(self.script):
            return AIMessage(content=REPLAY_FINISHED_CONTENT)
        call = self.script[turn]
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": call.name,
                    "args": dict(call.args),
                    "id": scripted_call_id(turn),
                    # LangChain strips and re-sets this key in a before-validator,
                    # so any written value is provably unobservable.
                    "type": "tool_call",  # pragma: no mutate
                }
            ],
        )
