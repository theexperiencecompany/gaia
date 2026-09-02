"""
Workflow Execution Models.

Models for tracking workflow execution history.
"""

from collections.abc import Callable
from datetime import datetime
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument

#: How much of a tool's result is kept on the record. Enough to tell the next run
#: what came back (ids, a count, a cursor) without storing message bodies — the
#: whole point is that a run's history stops growing with the number of runs.
RESULT_DIGEST_MAX_CHARS = 4000


def build_result_digest(output: object, max_chars: int = RESULT_DIGEST_MAX_CHARS) -> str:
    """A tool's result, always within ``max_chars`` and never cut mid-structure.

    The digest is not decoration. ``$last_run.<TOOL>.<path>`` resolves against
    it and a replay's narration reads it as what the tool returned, so a blind
    slice breaks both at once: JSON cut mid-token stops parsing, a cursor then
    silently resolves to nothing, and the narration describes a fragment as if
    it were the whole result. A JSON payload is therefore re-serialised compactly
    and, when it still does not fit, has its long strings cut and marked, then
    loses whole elements off the end rather than half of one. Only a result that
    is not JSON is truncated as text.

    The bound is guaranteed for every input: ``RecordedCall.result_digest``
    enforces it, and a record that fails to build after the tool already ran
    loses the trace the run was keeping.

    The record uses the default bound so history stops growing with the number
    of runs; a reader that writes from the result (a replay's narration) passes
    a bound sized for what a model can read, not for what a document can hold.
    """
    if output is None:
        return ""
    text = output if isinstance(output, str) else str(output)
    if len(text) <= max_chars:
        return text
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text[:max_chars]
    return _bounded_json(value, max_chars)


def _compact(value: object) -> str:
    """Compact JSON, so the bound buys content rather than whitespace."""
    return json.dumps(value, separators=(",", ":"))


#: Longest string a value keeps once it has to be trimmed to fit. Ids, subjects
#: and dates survive whole; a body is cut, and says so.
_ELEMENT_STRING_MAX_CHARS = 200
RECORD_CUT_MARKER = "…[cut]"
_CUT_MARKER = RECORD_CUT_MARKER


def _trim_strings(value: object, limit: int) -> object:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + _CUT_MARKER
    if isinstance(value, list):
        return [_trim_strings(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _trim_strings(item, limit) for key, item in value.items()}
    return value


def _fit_elements(
    items: list[Any], rebuild: Callable[[list[Any]], object], max_chars: int
) -> str | None:
    """The value with elements shed off the end until it fits; ``None`` when not
    even the first element fits, so the caller keeps cutting strings instead of
    recording a list that had items as an empty one."""
    kept: list[Any] = []
    for item in items:
        kept.append(item)
        if len(_compact(rebuild(kept))) > max_chars:
            kept.pop()
            break
    if items and not kept:
        return None
    return _compact(rebuild(kept))


def _bounded_json(value: object, max_chars: int) -> str:
    """``value`` as compact JSON within the bound, valid JSON wherever that is possible.

    Long strings are cut before any element is shed: three emails whose bodies
    each outweigh the bound must be recorded as three cut emails, not one whole
    one, because the ids and subjects are the record and the bodies are not.
    The cut applies to the whole value, so a big non-list sibling (a page's
    ``html`` beside its ``links``) cannot hold the digest over the bound. When
    that still does not fit, whole elements are shed off the end of the largest
    list; when even that is not enough the string limit halves and both steps
    repeat, down to strings that are only their cut marker. A value with no
    strings left to cut and still too big is the one case sliced as text.
    """
    digest = _compact(value)
    if len(digest) <= max_chars:
        return digest
    limit = _ELEMENT_STRING_MAX_CHARS
    while True:
        trimmed = _trim_strings(value, limit)
        items, rebuild = _largest_sequence(trimmed)
        fitted = _compact(trimmed) if items is None else _fit_elements(items, rebuild, max_chars)
        if fitted is not None:
            digest = fitted
            if len(digest) <= max_chars:
                return digest
        if limit == 0:
            return digest[:max_chars]
        limit //= 2


def _as_is(items: list[Any]) -> object:
    return items


def _largest_sequence(
    value: object,
) -> tuple[list[Any] | None, Callable[[list[Any]], object]]:
    """The list inside ``value`` worth shedding, and how to put it back.

    Searched at any depth under dicts, because tool results are envelopes: the
    list that carries the bulk sits under ``data``, and a search that stopped
    at the top level found nothing to shed and fell back to a blind slice.
    """
    if isinstance(value, list):
        return value, _as_is
    if not isinstance(value, dict):
        return None, _as_is

    best: list[Any] | None = None
    best_rebuild: Callable[[list[Any]], object] = _as_is
    # Any sentinel below 2 is equivalent: a candidate is compact JSON of a list,
    # never shorter than "[]", so the first one always wins the comparison.
    best_size = -1  # pragma: no mutate
    for key, child in value.items():
        items, rebuild_child = _largest_sequence(child)
        if items is None:
            continue
        size = len(_compact(items))
        if size > best_size:
            best, best_size = items, size

            def rebuild(
                replacement: list[Any],
                key: str = key,
                rebuild_child: Callable[[list[Any]], object] = rebuild_child,
            ) -> object:
                return {**value, key: rebuild_child(replacement)}

            best_rebuild = rebuild
    return best, best_rebuild


def largest_list_len(value: object) -> int | None:
    """Length of the largest list anywhere inside ``value``; ``None`` when it has none.

    Tool results are envelopes (``{"data": {"messages": [...]}}``), so "did this
    call return any items" has to look past the top level. Shared by the replay's
    empty-result check and the handoff call record, so both agree on what empty
    means.
    """
    best: int | None = None
    if isinstance(value, list):
        best = len(value)
        children: list[object] = value
    elif isinstance(value, dict):
        children = list(value.values())
    else:
        return None
    for child in children:
        nested = largest_list_len(child)
        # On a tie, re-assigning an equal int is a no-op, so > and >= are
        # equivalent here; the strict form documents first-wins.
        if nested is not None and (best is None or nested > best):  # pragma: no mutate
            best = nested
    return best


# The run-states an execution record may hold: created as ``running``, then
# exactly one terminal write. Named once here because the document, the update
# model, the repository's ``complete`` and the service's ``complete_execution``
# all speak it (Type Safety items 3 and 5).
#: ``skipped``: the fire never ran because another run of the same workflow
#: was in flight; that run delivered the result. Not a failure to show in red.
WorkflowExecutionStatus = Literal["running", "success", "failed", "skipped"]


class RecordedCall(BaseModel):
    """One tool call as it actually ran.

    Captured from the run's own tool events — the same stream the chat UI
    renders — so recording costs nothing beyond persisting what was already
    collected. ``args`` is what makes this useful: it is the material an agent
    reads to author a playbook, and the cursor a later run picks up from.
    """

    model_config = ConfigDict(extra="ignore")

    tool_name: str
    tool_category: str = ""
    #: Which subagent ran it, so a recorded handoff keeps its children — a trace
    #: flattened to the executor level is just one ``handoff`` call and useless.
    subagent_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    result_digest: str = Field(
        default="", max_length=RESULT_DIGEST_MAX_CHARS, description="Bounded result summary"
    )
    #: True when a playbook replay made the call. The replay's empty-vs-previous
    #: check compares only against replayed calls: an agent run probes the same
    #: tool broadly, and its full result is not what the frozen call returned.
    replayed: bool = False


class WorkflowExecution(BaseModel):
    """A single workflow execution record."""

    execution_id: str = Field(description="Unique execution identifier")
    workflow_id: str = Field(description="ID of the workflow that was executed")
    user_id: str = Field(description="ID of the user who owns the workflow")
    status: WorkflowExecutionStatus = Field(
        default="running", description="Current status of the execution"
    )
    started_at: datetime = Field(description="When the execution started")
    completed_at: datetime | None = Field(default=None, description="When the execution completed")
    duration_seconds: float | None = Field(
        default=None, description="Execution duration in seconds"
    )
    conversation_id: str | None = Field(
        default=None, description="Conversation containing the full execution"
    )
    summary: str | None = Field(
        default=None, description="Brief summary of what the execution accomplished"
    )
    error_message: str | None = Field(default=None, description="Error message if execution failed")
    trigger_type: str = Field(
        default="manual",
        description="What triggered the execution: manual, schedule, or integration name",
    )
    #: What this run actually did, in order. Replaces the LangGraph checkpoint as
    #: the way a workflow remembers itself: the previous run's trace is injected
    #: into the next run's opening message, so history stops being re-sent as a
    #: full transcript on every fire.
    trace: list[RecordedCall] = Field(default_factory=list)


class WorkflowExecutionsResponse(BaseModel):
    """Response for workflow executions list endpoint."""

    executions: list[WorkflowExecution] = Field(
        default_factory=list, description="List of workflow executions"
    )
    total: int = Field(default=0, description="Total number of executions")
    has_more: bool = Field(default=False, description="Whether there are more executions to load")


class WorkflowExecutionDocument(WorkflowExecution, MongoDocument):
    """A workflow execution as stored in MongoDB.

    Identity is the business key ``execution_id``; Mongo's ``_id`` is an
    incidental ObjectId and the inherited ``id`` is unused. Being a subclass of
    ``WorkflowExecution`` it doubles as the API/read model directly.
    """


class WorkflowExecutionUpdate(BaseModel):
    """Partial ``$set`` update for an execution — the completion fields."""

    model_config = ConfigDict(extra="forbid")

    status: WorkflowExecutionStatus | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    error_message: str | None = None
    conversation_id: str | None = None
    trace: list[RecordedCall] | None = None
