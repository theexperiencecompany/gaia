"""Ask the model for a structured answer, check it in code, and salvage the brief when the model never passes.

The one policy for every checked call a brief makes (its composition and its voice): an answer
that is unreadable or fails its check goes back to the model with every problem named, up to
the call's attempts; when the last answer still fails, code builds the result from what holds
and the salvage is logged as an error. A salvage never asks a model, so it cannot fail: the
brief reaches the user correct, if plainer, and never fails for the model's sake.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, metered_config
from app.agents.llm.exceptions import MalformedStructuredOutputError
from shared.py.wide_events import log

S = TypeVar("S", bound=BaseModel)
R = TypeVar("R")

#: The provider holds every checked answer to its schema, so no weaker model can drop a field.
_SCHEMA_HELD = StructuredCallOptions(schema_held=True)
#: What a retry is shown of a reply that came back with nothing readable.
_NO_READABLE_REPLY = "(no readable reply)"


@dataclass(frozen=True)
class Rejected(Generic[S]):
    """An answer its check turned back: every problem, what the retry is told, and what holds of it."""

    problems: list[str]
    note: str
    #: What holds of the answer, which a salvage keeps; None when the salvage needs none.
    kept: S | None = None


@dataclass(frozen=True)
class CheckedCall(Generic[S, R]):
    """One checked structured call: what it asks for, how its answer is checked, how it is salvaged.

    name tags its log events (briefing.checked_call_*) and names its wide-event fields
    (brief_<name>); unreadable writes the retry's note for a reply that
    is no whole answer, from its problems and the reply.
    """

    name: str
    schema: type[S]
    label: str
    attempts: int
    check: Callable[[S], Awaitable[R | Rejected[S]]]
    unreadable: Callable[[list[str], str], str]
    salvage: Callable[[S | None], R]


def unreadable_problems(exc: MalformedStructuredOutputError) -> list[str]:
    """Name each field the reply got wrong, never its text; a reply with no answer at all, why."""
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return [exc.reason]
    errors: list[ErrorDetails] = cause.errors()
    return [f"{error['loc'][0]}: {error['msg']}" for error in errors]


@dataclass(frozen=True)
class _Unreadable:
    """A reply that was no whole answer: what it got wrong, and what came back."""

    problems: list[str]
    reply: str


async def _asked(user_id: str, prompt: str, call: CheckedCall[S, R]) -> S | _Unreadable:
    try:
        return await ainvoke_structured(
            call.schema,
            prompt,
            label=call.label,
            config=metered_config(user_id),
            options=_SCHEMA_HELD,
        )
    except MalformedStructuredOutputError as exc:
        return _Unreadable(unreadable_problems(exc), exc.llm_output or _NO_READABLE_REPLY)


async def checked_structured_call(user_id: str, prompt: str, call: CheckedCall[S, R]) -> R:
    """Ask, check and ask again with the problems named; past the last attempt, salvage in code.

    Briefing work, metered and never charged to the user's allowance.
    """
    note = ""
    rejections: list[str] = []
    for attempt in range(1, call.attempts + 1):
        answer = await _asked(user_id, f"{prompt}\n\n{note}" if note else prompt, call)
        if isinstance(answer, _Unreadable):
            # Logged by field, out of the except: the error's own text quotes the user's data.
            log.warning(
                "briefing.checked_call_unreadable", call=call.name, problems=answer.problems
            )
            rejections.append("; ".join(answer.problems))
            note, kept = call.unreadable(answer.problems, answer.reply), None
            continue
        checked = await call.check(answer)
        if not isinstance(checked, Rejected):
            log.set_ns(
                f"brief_{call.name}", attempts=attempt, salvaged=False, rejections=rejections
            )
            return checked
        log.warning("briefing.checked_call_rejected", call=call.name, problems=checked.problems)
        rejections.append("; ".join(checked.problems))
        note, kept = checked.note, checked.kept
    log.set_ns(f"brief_{call.name}", attempts=call.attempts, salvaged=True, rejections=rejections)
    log.error("briefing.checked_call_salvaged", call=call.name, problems=rejections[-1])
    return call.salvage(kept)
