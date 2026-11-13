"""Read the executor run trace back: read-only, and every read is scoped to the user's own runs."""

from dataclasses import dataclass

from app.constants.run_trace import RUN_TRACE_LIST_DEFAULT_LIMIT, RUN_TRACE_LIST_MAX_LIMIT
from app.db.repositories.run_traces import (
    call_payload_repository,
    run_call_repository,
    run_repository,
)
from app.models.run_trace_models import RunCallDocument, RunDocument


@dataclass(frozen=True, slots=True)
class CallDetail:
    """One call with the full input and output it was stored with."""

    call: RunCallDocument
    input_json: str
    output_text: str
    truncated: bool


def _bounded(limit: int) -> int:
    """Return limit held to the most one read may return; a limit below one is a caller bug."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    return min(limit, RUN_TRACE_LIST_MAX_LIMIT)


async def list_run_calls(
    user_id: str, run_id: str, *, limit: int = RUN_TRACE_LIST_DEFAULT_LIMIT
) -> list[RunCallDocument]:
    """List a run's calls in the order they started, without their inputs and outputs."""
    return await run_call_repository.list_for_run(user_id, run_id, limit=_bounded(limit))


async def get_call_detail(user_id: str, run_id: str, call_id: str) -> CallDetail | None:
    """Return one call with its full input and output; None when the user has no such call or it expired."""
    call = await run_call_repository.get_in_run(user_id, run_id, call_id)
    if call is None:
        return None
    payload = await call_payload_repository.get(call.payload_ref, user_id=user_id)
    if payload is None:
        return None
    return CallDetail(
        call=call,
        input_json=payload.input_json,
        output_text=payload.output_text,
        truncated=payload.truncated,
    )


async def list_conversation_runs(
    user_id: str, conversation_id: str, *, limit: int = RUN_TRACE_LIST_DEFAULT_LIMIT
) -> list[RunDocument]:
    """List the runs of one conversation, newest first."""
    return await run_repository.list_for_conversation(
        user_id, conversation_id, limit=_bounded(limit)
    )


async def list_todo_runs(
    user_id: str, todo_id: str, *, limit: int = RUN_TRACE_LIST_DEFAULT_LIMIT
) -> list[RunDocument]:
    """List the runs of one tracked todo, newest first."""
    return await run_repository.list_for_todo(user_id, todo_id, limit=_bounded(limit))
