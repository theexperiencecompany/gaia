"""Match a scout report's steps back to the calls its learn run made.

A scout freezes calls its learn run really made, so each step names one of them:
the same tool, with args the recorded call agrees with. The matched calls are the
sources validate_playbook checks the steps' results and $steps shapes against.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.models.playbook_models import ForEachStep, ToolStep, is_ask_slot, is_time_slot
from app.models.workflow_execution_models import parse_result
from app.services.workflow.playbook.parser import RecordedResult, rendered_args
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN


@dataclass(frozen=True, slots=True)
class LearnCall:
    """One answered call of the learn run: the tool, its args and its parsed answer."""

    tool_name: str
    args: Mapping[str, Any]
    result: object


def learn_calls(messages: Sequence[BaseMessage]) -> list[LearnCall]:
    """Return the run's answered tool calls, failed ones included, in call order."""
    answers: dict[str, object] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and message.tool_call_id:
            content = message.content
            answers[message.tool_call_id] = parse_result(
                content if isinstance(content, str) else json.dumps(content, default=str)
            )
    return [
        LearnCall(tool_name=call["name"], args=dict(call["args"]), result=answers[call["id"]])
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["name"] and call["id"] is not None and call["id"] in answers
    ]


def freeze_sources(
    steps: Sequence[ToolStep | ForEachStep], calls: Sequence[LearnCall]
) -> list[RecordedResult] | str:
    """Return the call each step froze, in step order, or why steps match none.

    Among the calls that agree with a step the last wins, and a call answers one step only.
    """
    used: set[int] = set()
    sources: list[RecordedResult] = []
    problems: list[str] = []
    for position, step in enumerate(steps):
        agreeing = [
            index
            for index, call in enumerate(calls)
            if index not in used and call.tool_name == step.tool and _args_agree(step, call)
        ]
        if not agreeing:
            problems.append(f"steps[{position}]: {_unmatched(step, calls, used)}")
            continue
        used.add(agreeing[-1])
        call = calls[agreeing[-1]]
        sources.append(RecordedResult(args=call.args, result=call.result))
    return "; ".join(problems) if problems else sources


def _args_agree(step: ToolStep | ForEachStep, call: LearnCall) -> bool:
    return all(
        key in call.args and _agrees(value, call.args[key]) for key, value in step.args.items()
    )


def _unmatched(step: ToolStep | ForEachStep, calls: Sequence[LearnCall], used: set[int]) -> str:
    """Return why no recorded call answers to this step: none made, all frozen already, or other args."""
    same_tool = [(index, call) for index, call in enumerate(calls) if call.tool_name == step.tool]
    if not same_tool:
        return (
            f"{step.tool} did not run in this run; a playbook freezes calls "
            "that ran and produced their result — run it, or drop the step"
        )
    left = [call for index, call in same_tool if index not in used]
    if not left:
        return (
            f"{step.tool} ran {len(same_tool)} time(s) in this run and earlier steps froze "
            "every one of them; a step cannot replay a call the run did not make — drop "
            "this step, or run it again"
        )
    return (
        f"{step.tool} ran {len(same_tool)} time(s) in this run, but never with these args "
        f"(the last call used {rendered_args(left[-1].args)}); freeze the call that ran, "
        "with the args that produced its result, or run it with these args"
    )


def _agrees(step_value: object, recorded_value: object) -> bool:
    """Whether a step's value could be the recorded one: a slot or a bare placeholder is anything."""
    if is_ask_slot(step_value) or is_time_slot(step_value):
        return True
    if isinstance(step_value, str):
        if PLACEHOLDER_TOKEN.fullmatch(step_value):
            return True
        if PLACEHOLDER_TOKEN.search(step_value):
            return isinstance(recorded_value, str)
        return step_value == recorded_value
    if isinstance(step_value, Mapping):
        return isinstance(recorded_value, Mapping) and all(
            key in recorded_value and _agrees(item, recorded_value[key])
            for key, item in step_value.items()
        )
    if isinstance(step_value, list):
        return (
            isinstance(recorded_value, list)
            and len(step_value) == len(recorded_value)
            and all(_agrees(a, b) for a, b in zip(step_value, recorded_value, strict=True))
        )
    return step_value == recorded_value
