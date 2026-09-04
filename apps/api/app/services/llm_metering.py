"""Pricing + recording for a single model call — the one write both metering
routes share.

Two seams produce LLM spend and neither can see the other:

- ``LLMAccountingMiddleware`` for everything that runs through an agent graph
  (chat, workflows, bots, voice, subagents), which also passes
  ``root_request_id`` so the call counts toward the per-request token ceiling.
  This route CHARGES the user's day/month budget windows — it is work the user
  actively asked for.
- ``ainvoke_structured`` for auxiliary one-shot calls (memory
  extraction/reconcile/consolidation, follow-ups, onboarding, workflow
  generation, …), which never reach the middleware. This route records spend
  for COGS observability only (``charge_to_budget=False``) — background work
  must never consume the user's allowance.

Both call :func:`record_llm_call`, so a call is priced and recorded identically
no matter where it originates; only whether it counts against the budget
differs, and each caller states that explicitly. Lives in its own module
because ``cost_budget`` cannot import ``config.model_pricing`` — that pulls in
``app.decorators``, which imports ``cost_budget`` right back.
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
    ``LLMInvokeOptions`` exists: the seam already sits at the repo's
    argument-count ceiling. Every field is what the CALL SITE knows and the
    metering seam cannot re-derive — the seam is shared by four routes that see
    very different amounts of context, so each states what it has and leaves the
    rest ``None`` instead of the seam guessing.

    Deliberately carries no message content. This object is what becomes an
    ``llm_calls`` ledger document, and that collection stores counts and
    identifiers only.
    """

    #: The lane label the ``llm_call`` wide event carries, verbatim.
    agent_name: str
    #: Auxiliary work GAIA chose to do, rather than the user's own turn.
    background: bool
    #: Whether this spend counts against the user's allowance (agent-graph work
    #: they asked for) or is auxiliary background COGS (recorded durably, never
    #: charged). Required, with no default, so every call site states it — it
    #: sits beside ``background`` because they are the same judgement about the
    #: same call, and keeping them apart is how they drift.
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

    ``job_id`` and the task name are stamped by ``arq_task``'s ``wide_task``
    boundary and ``workflow.execution_id`` by the workflow task — none of them
    exist in ``config.configurable``, so there is no call-site value to thread:
    the boundary's own ContextVar IS where they live, and it is the same one the
    ``llm_call`` log line is built from. Reading it here keeps the ledger and
    the wide event agreeing by construction. Empty outside a boundary (an HTTP
    request, a test), which reads back as ``None`` rather than a fabricated id.
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
    """Append one row to the ``llm_calls`` ledger, or warn and move on.

    This is the ONE place in the metering path allowed to degrade silently, and
    the reason is narrow: the ledger is an observability artifact, not the
    system of record. The money is already booked by ``record_model_call_usage``
    (Redis budget windows + the durable ``usage_daily`` rollup) and the call is
    already described by the ``llm_call`` wide event, so a Mongo blip costs a
    row of analytics — not a user's reply, and not a dollar. Raising here would
    take chat down to protect a metering table, which is exactly backwards.

    The failure is a ``log.warning``, not a swallow: it is greppable, it lands
    on the wide event, and a sustained gap between ``usage_daily`` and the
    ledger's own row count is measurable after the fact.
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

    ``usage`` carries the four counts every route prices from (see
    :class:`TokenUsage`): ``cached_tokens`` is the subset of ``input_tokens``
    that hit the provider's prompt cache — billed at the discounted rate, not
    free — and ``reasoning_tokens`` the subset of ``output_tokens`` spent on
    hidden thinking, when the provider reports it (not separately priced —
    already billed as output). All four ride alongside the cost into the
    durable rollup so a mispriced call can be re-derived from raw usage after
    the fact. Omit ``root_request_id``
    for work that is not bounded by a single agent tree. Fail-open: a pricing or
    write failure degrades cost to 0.0 and never fails a model call that
    already succeeded.

    ``context`` is the call's identity — lane, models, conversation, workflow,
    latency, and ``charge_to_budget`` (see :class:`LLMCallContext`). It is
    required, not optional: it is what becomes the call's ``llm_calls`` ledger
    row, and the ledger is only worth having if every route states what it
    knows. An optional argument is how the log lines ended up with no context
    ids on 55% of calls.
    """
    # What the provider says it charged always wins over what we would have
    # guessed. MODEL_PRICING carries ONE rate per model, but OpenRouter routes
    # each call to whichever upstream is free and their rates differ by more
    # than 10x (measured 2026-08-29: 0.030-0.440 USD per million input tokens
    # across the pool for a single model id). Pricing from the table therefore
    # mis-states every call in one direction or the other, and it under-stated
    # total spend by 44% over a 1,486-call window. The table stays as the
    # fallback for providers/lanes that report no cost.
    # ``isfinite`` before the sign check, because ``inf >= 0.0`` is true: a
    # malformed provider cost would otherwise bypass the table entirely and
    # write inf/nan into the budget windows and the durable rollup, where it
    # poisons every sum that touches that user-day. A non-finite value is not a
    # cost the provider reported, so it falls through to table pricing.
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
        # Pricing is pure computation over a model lookup — a failure here is an
        # unexpected bug (bad/missing pricing entry), not an infra blip, so it is
        # surfaced loudly and alertably. We still return 0.0 rather than raising:
        # the provider call already completed and charged, and raising would fail
        # the user's turn for a metering bug. The dropped spend is greppable via
        # this event so the budget under-count is visible, not silent.
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

    Called from the invoke seam AFTER the retry and fallback policy is spent, so
    this is one row per failed CALL, not per attempt — counting attempts here
    would multiply every outage by the retry budget and make the error rate a
    function of our own configuration.

    Books no money and no tokens. The attempts did burn tokens upstream, but
    nothing reported them (there is no usage payload on a failed call), and
    inventing a number would put fiction into the same column real spend is
    summed from. The budget windows and ``usage_daily`` are deliberately NOT
    touched: this writes to the ledger only.
    """
    family = classify_error_family(error)
    # Parity with every successful call. Without it a failure exists ONLY in the
    # ledger: the backfill reads log lines, so failures could never be
    # reconstructed from history, and an operator grepping ``llm_event=llm_call``
    # during an incident would see traffic drop rather than errors appear. Two
    # sources of truth that disagree about whether a call happened is worse than
    # one extra line.
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
    """Write one already-priced call to the budget windows, the durable rollup
    and the ``llm_calls`` ledger.

    Split out so the provider-reported and table-priced paths record through
    exactly the same seam — the only difference between them is where the
    dollar figure came from, which is exactly what ``cost_source`` records.

    The ledger insert is spawned rather than awaited: it is the one write here
    that nothing downstream depends on, and holding the user's turn open for a
    Mongo round-trip to write an analytics row would be paying latency for
    observability. Every field it needs is captured into the document BEFORE the
    spawn, so the row is a snapshot of this call and not of whatever context the
    task happens to run in.
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
        # Infra fail-open per the cost-budget module's documented degradation
        # philosophy (a Redis blip must never fail an already-completed call).
        # record_model_call_usage already fails open per-op internally; this is
        # the outer backstop.
        log.warning(
            f"{LogTag.AGENT} Cost/token budget recording failed (failing open)",
            error=str(e),
            error_type=type(e).__name__,
        )

    return call.total_cost


def extract_message_usage(message: AIMessage) -> TokenUsage:
    """Return input/output/cached/reasoning token counts from a message's usage metadata.

    Reads ``message.usage_metadata`` (the canonical LangChain shape) and falls
    back to ``response_metadata.usage_metadata`` for the provider SDK versions
    that only populate that. ``cached_tokens`` comes from
    ``input_token_details.cache_read`` or — when the provider surfaces it
    separately — ``cached_content_token_count``. ``reasoning_tokens`` (a
    subset of ``output_tokens`` spent on hidden thinking) comes from
    ``output_token_details.reasoning``; not every provider/model returns it.
    Missing fields default to 0.
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

    # Each field falls back independently. Gating the output fallback behind a
    # missing *input* count (as this once did) silently dropped output tokens —
    # and their cost — from every message that reported only one of the two.
    # Both `prompt_token_count`/`candidates_token_count` (provider-native shape)
    # and the LangChain-normalised keys are accepted.
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
    """What OpenRouter says this call actually cost, or ``None`` if it did not say.

    OpenRouter returns a real ``usage.cost`` only when the request carries
    ``usage: {"include": true}`` (see ``_usage_accounting_kwargs`` in
    ``agents/llm/client``); ``ChatOpenRouter`` copies it to
    ``response_metadata["cost"]``. Lanes that are not OpenRouter — direct
    Gemini, the sim lane — never populate it, and those keep falling back to
    :func:`app.config.model_pricing.calculate_token_cost`.

    A zero is a real answer (free/promotional routes exist) and is returned as
    ``0.0``; a missing, unparseable, negative or non-finite value returns
    ``None`` so the caller falls back to table pricing. ``float("inf")`` and
    ``float("nan")`` parse cleanly and ``inf >= 0.0`` is true, so they have to
    be rejected explicitly — otherwise a malformed provider payload becomes a
    non-finite dollar figure in the budget windows and the durable rollup.
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
    """The model the provider says served this call, or ``UNKNOWN_MODEL_NAME``.

    What the LANE asked for and what actually answered are different facts —
    a provider substitution or a fallback makes them diverge — and the ledger
    records both (``model_requested`` / ``model_served``), so the reply's own
    account of itself has to be readable here rather than inferred from the
    lane the caller configured.
    """
    resp_meta = message.response_metadata or {}
    return str(resp_meta.get("model_name") or "") or UNKNOWN_MODEL_NAME


def extract_generation_id(message: AIMessage) -> str | None:
    """The upstream generation id for this call, when the provider returned one.

    A second handle on *which upstream served the request*, alongside the name
    itself. OpenRouter names the serving upstream in a ``provider`` response
    field; ``ChatOpenRouter`` drops it and stamps ``model_provider`` as the
    literal ``"openrouter"``, so the aggregator's own name is all that reaches
    us out of the box — ``openrouter_provider_name_patch`` is what restores the
    real one, under ``response_metadata[PROVIDER_NAME_METADATA_KEY]``. The id
    stays worth carrying because it also resolves cost and routing detail the
    name alone does not. ``id`` survives both paths (``_create_chat_result`` puts it in
    ``llm_output``, which ``langchain_core`` merges into ``response_metadata``;
    ``_astream``/``_stream`` set ``generation_info["id"]`` directly), and it
    resolves to the serving upstream through OpenRouter's generation-metadata
    endpoint without spending a model call.

    Without it, a request that reports zero cached tokens is ambiguous: it may
    have landed on a different upstream (which holds no warm prefix at all) or
    the prompt prefix may have genuinely broken. Those have opposite fixes, so
    the id is what keeps a cache regression from being diagnosed by guesswork.
    """
    resp_meta = message.response_metadata or {}
    return str(resp_meta.get("id") or "") or None


def resolve_channel(configurable: Mapping[str, Any], *, background: bool = False) -> str | None:
    """Which surface originated this call, from the run's own configurable.

    ``background`` defaults to False because the graph and style-guard seams are
    the user's own turn by construction; only the auxiliary lane passes it, and
    it passes the run's real value.

    ``conversation_source`` is the value the entry point set — ``"web"`` /
    ``"desktop"`` from the chat endpoint's ``X-Client-Type`` header, or the bot
    platform (``"discord"``, ``"slack"``, ``"telegram"``, ``"whatsapp"``,
    ``"imessage"``) from the bot endpoint — and it is inherited by every child
    agent, so an executor call reports the surface its root turn came from.
    Never inferred from the agent name: ``comms_agent`` serves all of them.

    Background runs carry no ``conversation_source`` (nobody typed anything), so
    they are separated by what they DO carry: a run with a ``workflow_id`` is
    ``"workflow"``, and any other background work is ``"system"``. ``background``
    is passed explicitly because the auxiliary lanes (memory, chatbot,
    follow-ups) carry no ``source_category`` either — keying only on that field
    left 11 of 27 rows null in a live session, which is neither of the two
    answers the rule promises.

    ``None`` only for a foreground call that named no surface anywhere.

    KNOWN GAP: voice reports ``"web"``. The LiveKit agent posts to the same chat
    endpoint without an ``X-Client-Type`` header, so the header-based resolution
    cannot tell it apart; distinguishing it needs a change in the voice worker,
    not here, and guessing would be worse than the honest "web".
    """
    source = configurable.get("conversation_source")
    if source:
        return str(source)
    # The enclosing run's boundary, for calls whose own config carries nothing.
    # An auxiliary one-shot made INSIDE an executor run gets a bare config, so
    # without this a user's web turn is recorded as ``system`` — and it is the
    # executor turns that cost the most, so the under-count lands exactly where
    # COGS-by-channel matters. The run's own configurable still wins above.
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

    ``ChatOpenRouter`` merges ``generation_info`` into ``response_metadata`` on
    the STREAMING path, so ``finish_reason`` is there for every graph call. On
    the non-streaming path it stays in ``generation_info``, which never reaches
    an ``AIMessage`` — only ``native_finish_reason`` is copied onto the message.
    That upstream-specific value is the honest second-best here, so it is the
    fallback; the auxiliary route does better by reading ``generation_info``
    directly off the ``LLMResult`` (see ``_GenerationIdCallback``).

    Worth recording because a run of ``length`` on one lane is a truncation bug,
    and today it surfaces only as users reporting answers that stop mid-sentence.
    """
    resp_meta = message.response_metadata or {}
    reason = resp_meta.get("finish_reason") or resp_meta.get("native_finish_reason")
    return str(reason) or None if reason else None


def classify_error_family(error: BaseException) -> ErrorFamily:
    """Bucket a failed provider call by exception TYPE.

    Never by message text. Provider messages embed model ids, request ids and
    prompt fragments, they change without notice, and grouping on them yields a
    long tail of near-duplicates instead of the handful of buckets an operator
    can act on: throttled, timed out, upstream down, our request was wrong.

    Order matters — the rate-limit and timeout types are also members of broader
    unavailability sets, and the specific answer is the useful one.
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
    """The UPSTREAM that served this call — "Baidu", "StreamLake", "Fireworks".

    Read from ``response_metadata[PROVIDER_NAME_METADATA_KEY]``, which
    ``openrouter_provider_name_patch`` restores on both the streaming and
    non-streaming paths. Out of the box ``ChatOpenRouter`` drops OpenRouter's
    ``provider`` response field and stamps ``model_provider`` with the literal
    ``"openrouter"``, so without that patch the aggregator's own name was all
    that reached us and this column was always null.

    That name is still rejected explicitly if it ever arrives: the aggregator is
    not an upstream, and recording it would make every row claim a provider we
    never learned — a ``group by provider`` over the ledger would read as one
    homogeneous pool, when the entire point of the field is that the pool's
    rates differ by more than 10x for the same model id.

    ``None`` on the lanes the patch does not cover (direct Gemini, the sim
    lane), which genuinely have no upstream to name. Never guessed from the
    model id; :func:`extract_generation_id` remains the second handle, resolving
    routing detail the name alone does not carry.
    """
    resp_meta = message.response_metadata or {}
    reported = str(resp_meta.get(PROVIDER_NAME_METADATA_KEY) or "").strip()
    if not reported or reported.lower() == OPENROUTER_PROVIDER:
        return None
    return reported
