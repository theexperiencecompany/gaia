"""Pricing and recording for a single model call — the one write both metering routes share.

Two seams produce LLM spend and neither can see the other: LLMAccountingMiddleware
charges the user's day/month budget for everything run through an agent graph
(also passing root_request_id for the per-request token ceiling); ainvoke_structured
records auxiliary one-shot calls (memory, follow-ups, onboarding, workflow
generation) for COGS observability only (charge_to_budget=False), since
background work must never consume the user's allowance.

Both call record_llm_call, so pricing/recording is identical regardless of
origin; only whether it counts against budget differs, stated explicitly by
each caller. Lives here rather than in cost_budget because cost_budget cannot
import config.model_pricing (which imports app.decorators, which imports
cost_budget back).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Any, TypedDict

from google.genai.errors import ServerError as GeminiServerError
from langchain_core.messages import AIMessage
from openrouter.errors import (
    BadGatewayResponseError,
    BadRequestResponseError,
    EdgeNetworkTimeoutResponseError,
    ForbiddenResponseError,
    InternalServerResponseError,
    NoResponseError,
    NotFoundResponseError,
    PayloadTooLargeResponseError,
    PaymentRequiredResponseError,
    ProviderOverloadedResponseError,
    RequestTimeoutResponseError,
    ServiceUnavailableResponseError,
    TooManyRequestsResponseError,
    UnauthorizedResponseError,
    UnprocessableEntityResponseError,
)

from app.config.model_pricing import calculate_token_cost
from app.constants.llm import (
    OPENROUTER_PROVIDER,
    PROVIDER_NAME_METADATA_KEY,
    UNKNOWN_MODEL_NAME,
)
from app.constants.log_tags import LogTag
from app.db.repositories.llm_calls import (
    CallStatus,
    CostSource,
    ErrorFamily,
    LLMCallDocument,
    llm_calls_repository,
    split_lane_thread,
)
from app.db.repositories.usage_daily import UsageDailyIncrement
from app.services.cost_budget import record_model_call_usage
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import current_workflow_execution_id, log

# Exception types per :func:`classify_error_family`. Curated tuples rather than
# message matching, and ordered most-specific-first at the call site.
_RATE_LIMIT_ERRORS: tuple[type[BaseException], ...] = (TooManyRequestsResponseError,)
_TIMEOUT_ERRORS: tuple[type[BaseException], ...] = (
    RequestTimeoutResponseError,
    EdgeNetworkTimeoutResponseError,
    # asyncio.TimeoutError IS TimeoutError on 3.11+, so the invoke seam's own
    # wall-clock ceiling lands here too.
    TimeoutError,
)
_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    InternalServerResponseError,
    BadGatewayResponseError,
    ServiceUnavailableResponseError,
    ProviderOverloadedResponseError,
    NoResponseError,
    GeminiServerError,
    ConnectionError,
)
_INVALID_REQUEST_ERRORS: tuple[type[BaseException], ...] = (
    BadRequestResponseError,
    UnprocessableEntityResponseError,
    UnauthorizedResponseError,
    ForbiddenResponseError,
    NotFoundResponseError,
    PayloadTooLargeResponseError,
    # Out of credits is our account being wrong, not the upstream being down.
    PaymentRequiredResponseError,
)


#: ``SourceCategory.BG`` — the category every non-interactive run falls into.
_BACKGROUND_SOURCE_CATEGORY = "bg"


class TokenUsage(TypedDict):
    """The four token counts every metering route prices a call from."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int


@dataclass(frozen=True)
class LLMCallContext:
    """Everything about a model call that is NOT its price or its token counts.

    One object rather than a dozen keyword arguments, for the same reason
    LLMInvokeOptions exists: the seam already sits at the repo's
    argument-count ceiling. Every field is what the CALL SITE knows and the
    metering seam cannot re-derive — the seam is shared by four routes that see
    very different amounts of context, so each states what it has and leaves the
    rest None instead of the seam guessing.

    Deliberately carries no message content. This object is what becomes an
    llm_calls ledger document, and that collection stores counts and
    identifiers only.
    """

    #: The lane label the ``llm_call`` wide event carries, verbatim.
    agent_name: str
    #: Auxiliary work GAIA chose to do, rather than the user's own turn.
    background: bool
    #: Whether this spend counts against the user's allowance (agent-graph work
    #: they asked for) or is auxiliary background COGS (recorded, never charged).
    #: Required, with no default, so every call site states it explicitly.
    charge_to_budget: bool
    #: The model the provider says answered (``extract_message_model``).
    model_served: str | None = None
    #: The serving UPSTREAM when the response names one — see
    #: ``LLMCallDocument.provider`` for why this is almost always ``None``.
    provider: str | None = None
    #: OpenRouter's generation id (``extract_generation_id``).
    generation_id: str | None = None
    #: The TRUE conversation id when the call site holds one. Falls back to the
    #: id derived from ``thread_id``.
    conversation_id: str | None = None
    #: LangGraph's checkpoint thread, wrapper included.
    thread_id: str | None = None
    workflow_id: str | None = None
    #: Wall time of the provider call, where the seam wraps the invocation.
    duration_ms: float | None = None
    #: Why the provider stopped generating (``extract_finish_reason``).
    finish_reason: str | None = None
    #: The surface this call originated from. Threaded from the request or bot
    #: adapter that started the run — never inferred from the agent name, which
    #: is the same on every surface.
    channel: str | None = None


@dataclass(frozen=True)
class _PricedCall:
    """One model call after pricing — the shared input of both internal writes.

    Grouped rather than passed as eight parallel keywords so the rollup write
    and the ledger write cannot be handed different versions of the same call.
    """

    user_id: str | None
    model_name: str
    usage: TokenUsage
    root_request_id: str | None
    total_cost: float
    #: Whether ``total_cost`` came from the provider or from our price table.
    cost_source: CostSource
    #: How the call ended. An error row books no money and no tokens; it exists
    #: so a provider outage reads as a spike in failures rather than a silent
    #: dip in traffic.
    status: CallStatus = "ok"
    error_family: ErrorFamily | None = None


def _ambient_worker_context() -> dict[str, str | None]:
    """Worker/workflow identity for the call in flight, from the wide event.

    job_id/task_name come from arq_task's wide_task boundary,
    workflow_execution_id from the workflow task — the same ContextVar the
    llm_call log line is built from, so the ledger and wide event agree by
    construction. Empty (None) outside a boundary.
    """
    fields = log.get()
    return {
        "workflow_execution_id": current_workflow_execution_id(),
        "job_id": str(fields["job_id"]) if fields.get("job_id") else None,
        "task_name": str(fields["task"]) if fields.get("task") else None,
    }


def _build_ledger_document(call: _PricedCall, context: LLMCallContext) -> LLMCallDocument:
    """Assemble one ledger row. Pure — no I/O, so it is directly testable."""
    usage = call.usage
    lane = split_lane_thread(context.thread_id)
    ambient = _ambient_worker_context()
    return LLMCallDocument(
        created_at=datetime.now(UTC),
        user_id=call.user_id,
        agent_name=context.agent_name,
        background=context.background,
        charge_to_budget=context.charge_to_budget,
        model_requested=call.model_name,
        model_served=context.model_served,
        provider=context.provider,
        input_tokens=usage["input_tokens"],
        cached_tokens=usage["cached_tokens"],
        output_tokens=usage["output_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        cost_usd=call.total_cost,
        cost_source=call.cost_source,
        status=call.status,
        error_family=call.error_family,
        generation_id=context.generation_id,
        conversation_id=context.conversation_id or lane.conversation_id,
        lane_thread=lane.lane_thread,
        root_request_id=call.root_request_id,
        workflow_id=context.workflow_id,
        workflow_execution_id=ambient["workflow_execution_id"],
        job_id=ambient["job_id"],
        task_name=ambient["task_name"],
        channel=context.channel,
        duration_ms=context.duration_ms,
        finish_reason=context.finish_reason,
    )


async def _insert_ledger_row(doc: LLMCallDocument) -> None:
    """Append one row to the llm_calls ledger, or warn and move on.

    The one place allowed to degrade silently: money is already booked by
    record_model_call_usage and the call is already in the llm_call wide
    event, so a Mongo blip costs only an analytics row. Logged as a warning,
    not swallowed, so a sustained gap is measurable.
    """
    try:
        await llm_calls_repository.create(doc)
    except Exception as e:
        log.warning(
            f"{LogTag.MONGO} llm_calls ledger insert failed — the call is still "
            "priced, budgeted and on the wide event; only its ledger row is missing",
            agent_name=doc.agent_name,
            model=doc.model_requested,
            error=str(e),
            error_type=type(e).__name__,
        )


async def record_llm_call(
    *,
    user_id: str | None,
    model_name: str,
    usage: TokenUsage,
    root_request_id: str | None = None,
    provider_cost: float | None = None,
    context: LLMCallContext,
) -> float:
    """Price one model call and record its spend + tokens. Returns the USD cost.

    cached_tokens is billed at the discounted rate (not free); reasoning_tokens
    is already billed as output. context is required — optional left 55% of
    calls with no context ids. Fail-open: a pricing/write failure records cost
    as 0.0 without failing an already-succeeded call.
    """
    # Provider cost wins: upstream rates vary >10x (0.030-0.440 USD/M input,
    # measured 2026-08-29), under-stating spend 44% when priced from the table.
    # isfinite guards `inf >= 0.0`; a non-finite cost falls through to the table.
    if provider_cost is not None and math.isfinite(provider_cost) and provider_cost >= 0.0:
        return await _record(
            _PricedCall(
                user_id=user_id,
                model_name=model_name,
                usage=usage,
                root_request_id=root_request_id,
                total_cost=float(provider_cost),
                cost_source="provider",
            ),
            context,
        )

    try:
        cost = calculate_token_cost(
            model_name=model_name,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_tokens=usage["cached_tokens"],
        )
        total_cost = float(cost.get("total_cost", 0.0))
    except Exception as e:
        # A pricing failure is an unexpected bug, not an infra blip — surfaced via
        # log.error. Returns 0.0 rather than raising since the call already
        # completed/charged; the dropped spend stays greppable so the under-count is visible.
        log.error(
            f"{LogTag.AGENT} Token cost calc failed — spend recorded as $0 "
            "(budget will under-count this call)",
            model=model_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        total_cost = 0.0

    return await _record(
        _PricedCall(
            user_id=user_id,
            model_name=model_name,
            usage=usage,
            root_request_id=root_request_id,
            total_cost=total_cost,
            cost_source="table",
        ),
        context,
    )


async def record_failed_llm_call(
    *,
    user_id: str | None,
    model_name: str,
    error: BaseException,
    context: LLMCallContext,
) -> None:
    """Record one provider call that never answered.

    Called after the retry/fallback policy is spent, so this is one row per
    failed call, not per attempt. Books no money and no tokens — none were
    reported on a failed call, and inventing a number would pollute real
    spend; budget windows and usage_daily are not touched, only the ledger.
    """
    family = classify_error_family(error)
    # Parity with successful calls: without this log line a failure exists only
    # in the ledger, so the backfill (reads log lines) can't reconstruct it and
    # an incident grep for llm_event=llm_call would show traffic drop, not errors.
    log.info(
        "llm_call",
        llm_event="llm_call",
        status="error",
        error_family=family,
        error_type=type(error).__name__,
        agent_name=context.agent_name,
        background=context.background,
        model=model_name,
        user_id=user_id,
        conversation_id=context.conversation_id,
        channel=context.channel,
        generation_id=context.generation_id,
        duration_ms=context.duration_ms,
        # Zeroes so a failure sums alongside the successes without inflating
        # anything: nothing reported what the attempts burned.
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        cost_usd=0.0,
    )
    spawn_background_task(
        _insert_ledger_row(
            _build_ledger_document(
                _PricedCall(
                    user_id=user_id,
                    model_name=model_name,
                    usage=TokenUsage(
                        input_tokens=0, output_tokens=0, cached_tokens=0, reasoning_tokens=0
                    ),
                    root_request_id=None,
                    total_cost=0.0,
                    # Nothing was priced, so neither source is true. "table" is
                    # the honest one: no provider figure was ever reported.
                    cost_source="table",
                    status="error",
                    error_family=family,
                ),
                context,
            )
        ),
        name="llm_calls_ledger_error_insert",
    )


async def _record(call: _PricedCall, context: LLMCallContext) -> float:
    """Write one already-priced call to the budget windows, rollup and ledger.

    Ledger insert is spawned, not awaited — nothing downstream depends on it,
    and awaiting would pay chat latency for an analytics write. Fields are
    captured before the spawn, so the row snapshots this call, not whatever
    context the task runs in.
    """
    spawn_background_task(
        _insert_ledger_row(_build_ledger_document(call, context)),
        name="llm_calls_ledger_insert",
    )

    usage = call.usage
    try:
        await record_model_call_usage(
            call.user_id,
            UsageDailyIncrement(
                cost=call.total_cost,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cached_tokens=usage["cached_tokens"],
                reasoning_tokens=usage["reasoning_tokens"],
            ),
            call.root_request_id,
            charge_to_budget=context.charge_to_budget,
        )
    except Exception as e:
        # Fail-open: a Redis blip must never fail an already-completed call.
        # record_model_call_usage already fails open per-op; this is the outer backstop.
        log.warning(
            f"{LogTag.AGENT} Cost/token budget recording failed (failing open)",
            error=str(e),
            error_type=type(e).__name__,
        )

    return call.total_cost


def extract_message_usage(message: AIMessage) -> TokenUsage:
    """Return input/output/cached/reasoning token counts from a message's usage metadata.

    Reads message.usage_metadata, falling back to response_metadata.usage_metadata
    for providers that only populate that. cached_tokens comes from
    input_token_details.cache_read or cached_content_token_count;
    reasoning_tokens from output_token_details.reasoning. Missing fields default to 0.
    """
    # Annotated as a plain mapping: the TypedDict cannot represent the empty
    # fallback, and every read below already defaults each key.
    usage: Mapping[str, Any] = message.usage_metadata or {}
    resp_meta = message.response_metadata or {}
    resp_usage = resp_meta.get("usage_metadata") or {}

    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cached_tokens = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
    reasoning_tokens = int((usage.get("output_token_details") or {}).get("reasoning") or 0)

    # Each field falls back independently — gating the output fallback behind a
    # missing input count once silently dropped output tokens (and their cost).
    # Both provider-native and LangChain-normalised key names are accepted.
    if not input_tokens:
        input_tokens = int(
            resp_usage.get("prompt_token_count", resp_usage.get("input_tokens", 0)) or 0
        )
    if not output_tokens:
        output_tokens = int(
            resp_usage.get("candidates_token_count", resp_usage.get("output_tokens", 0)) or 0
        )
    if not cached_tokens:
        cached_tokens = int(resp_usage.get("cached_content_token_count") or 0)

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def extract_message_cost(message: AIMessage) -> float | None:
    """Return what OpenRouter says this call actually cost, or None if it did not say.

    Populated only when the request carries usage: {"include": true}; other
    lanes (direct Gemini, sim) never set it and fall back to table pricing.
    Zero is a real answer (free routes exist); missing, unparseable,
    negative, or non-finite (inf/nan parse cleanly) returns None.
    """
    resp_meta = message.response_metadata or {}
    raw = resp_meta.get("cost")
    if raw is None:
        return None
    try:
        cost = float(raw)
    except (TypeError, ValueError):
        return None
    return cost if math.isfinite(cost) and cost >= 0.0 else None


def extract_message_model(message: AIMessage) -> str:
    """Return the model the provider says served this call, or UNKNOWN_MODEL_NAME.

    Requested and served models can diverge (substitution/fallback); the
    ledger records both, so the reply's own account has to be readable here.
    """
    resp_meta = message.response_metadata or {}
    return str(resp_meta.get("model_name") or "") or UNKNOWN_MODEL_NAME


def extract_generation_id(message: AIMessage) -> str | None:
    """Return the upstream generation id for this call, when the provider returned one.

    Resolves cost/routing detail the model name alone doesn't, via
    OpenRouter's generation-metadata endpoint (no extra model call). Without
    it, zero cached tokens is ambiguous — different upstream (no warm
    prefix) vs a broken prompt prefix — and those have opposite fixes.
    """
    resp_meta = message.response_metadata or {}
    return str(resp_meta.get("id") or "") or None


def resolve_channel(configurable: Mapping[str, Any], *, background: bool = False) -> str | None:
    """Which surface originated this call, from the run's own configurable.

    conversation_source comes from the entry point (client-type header or bot
    platform), inherited by every child agent. Background runs carry none;
    workflow_id gives "workflow", else "system" if marked explicitly (keying
    only on source_category left 11/27 rows null). KNOWN GAP: voice reports "web".
    """
    source = configurable.get("conversation_source")
    if source:
        return str(source)
    # Enclosing run's boundary, for calls with a bare config (an auxiliary
    # one-shot inside an executor run) — without it a user's web turn records
    # as "system", undercounting exactly where executor COGS-by-channel matters.
    ambient = log.get().get("conversation_source")
    if ambient:
        return str(ambient)
    if configurable.get("workflow_id"):
        return "workflow"
    if background or configurable.get("source_category") == _BACKGROUND_SOURCE_CATEGORY:
        return "system"
    return None


def extract_finish_reason(message: AIMessage) -> str | None:
    """Why the provider stopped generating, when the reply says.

    finish_reason is present on the streaming path; on non-streaming it
    stays in generation_info (never reaches an AIMessage), so this falls
    back to the upstream-specific native_finish_reason instead.
    """
    resp_meta = message.response_metadata or {}
    reason = resp_meta.get("finish_reason") or resp_meta.get("native_finish_reason")
    return str(reason) or None if reason else None


def classify_error_family(error: BaseException) -> ErrorFamily:
    """Bucket a failed provider call by exception TYPE, never by message text.

    Provider messages embed ids/prompt fragments that change without notice,
    so type gives the handful of actionable buckets. Order matters:
    rate-limit and timeout types are also members of broader unavailability sets.
    """
    if isinstance(error, _RATE_LIMIT_ERRORS):
        return "rate_limit"
    if isinstance(error, _TIMEOUT_ERRORS):
        return "timeout"
    if isinstance(error, _UNAVAILABLE_ERRORS):
        return "provider_unavailable"
    if isinstance(error, _INVALID_REQUEST_ERRORS):
        return "invalid_request"
    return "other"


def extract_message_provider(message: AIMessage) -> str | None:
    """Return the UPSTREAM that served this call — "Baidu", "StreamLake", "Fireworks".

    Read from response_metadata[PROVIDER_NAME_METADATA_KEY], restored by
    openrouter_provider_name_patch (ChatOpenRouter otherwise stamps the
    literal "openrouter", rejected here as it would homogenize the >10x rate
    spread the field exists to track). None on lanes the patch doesn't cover.
    """
    resp_meta = message.response_metadata or {}
    reported = str(resp_meta.get(PROVIDER_NAME_METADATA_KEY) or "").strip()
    if not reported or reported.lower() == OPENROUTER_PROVIDER:
        return None
    return reported
