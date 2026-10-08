"""The dispatch core: resolve → validate → invoke, for both execute surfaces.

The LLM-facing ``execute`` tool and the sandbox code-mode route both call
``dispatch_tool`` — there is exactly one place a proxied tool is resolved,
validated and run, so classification, analytics and error shapes cannot drift
between the two surfaces.

Predictable failures (unknown tool, out-of-scope tool, args that fail the
schema, a tool that outruns the execution bound) return a structured error the
model can act on. Other infrastructure failures propagate to the caller's error
handling (the ToolNode's error formatting, the route's 500) — they are not the
model's mistake to correct.
"""

import asyncio
from collections.abc import Container
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from prometheus_client import Counter
from pydantic import BaseModel, ValidationError

from app.agents.tools.execute.resolver import ResolvedTool, resolve_tool
from app.config.oauth_config import get_integration_by_tool_slug
from app.constants.execute import (
    TICKET_APPROVE_NAME,
    TICKET_NAMES,
    TICKET_REVOKE_NAME,
)
from app.constants.integrations import ACCOUNT_NEEDS_RECONNECT_HINT
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS, TOOL_TIMEOUT_EXEMPT_TOOLS
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.integration_models import UserIntegrationDocument
from app.models.integrations.composio_hooks import ComposioAccountSelection
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.integrations.integration_accounts import (
    get_account_record,
    match_account,
    primary_account,
)
from app.services.storage.metrics import _register_once
from app.services.tool_shape_service import record_observed_shape
from shared.py.wide_events import log, spawn_logged_task

# Health metric of the proxy migration: invalid_args/ok is the
# retries-per-successful-action ratio. Charted in Grafana; labels are the
# closed outcome set below, never tool names (unbounded cardinality).
_EXECUTE_DISPATCH_TOTAL = _register_once(
    "gaia_execute_dispatch_total",
    lambda: Counter(
        "gaia_execute_dispatch_total",
        "Proxied tool dispatches by outcome",
        ["outcome"],
    ),
)


class DispatchErrorKind(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGS = "invalid_args"
    # An internal tool reached a surface (the sandbox route) that only runs
    # integration tools — internal tools need graph runtime and stay in-graph.
    INTERNAL_TOOL = "internal_tool"
    # A registered tool outside the calling agent's tool space (a subagent
    # reaching for another integration's tools).
    OUT_OF_SCOPE = "out_of_scope"
    # `account` names no connected account of the tool's integration, or names
    # one on a tool that has no accounts to choose between.
    UNKNOWN_ACCOUNT = "unknown_account"
    # The chosen account's grant died while another account still works.
    ACCOUNT_EXPIRED = "account_expired"
    # The tool did not return within the host's bound. Its own outcome is
    # unknown, so this is the one failure a retry can duplicate.
    TIMEOUT = "timeout"


class DispatchError(BaseModel):
    kind: DispatchErrorKind
    detail: str
    hint: str


class ToolExecutionResult(BaseModel):
    """Outcome of one proxied tool run; ``output`` is the tool's own payload."""

    ok: bool
    resolved_name: str
    # Tool outputs are genuinely schemaless here — each integration returns its
    # own shape and the proxy must pass it through unaltered (boundary, item 8).
    output: Any = None
    error: DispatchError | None = None
    # The account the call ran as, named only when the user has several on that integration.
    account: str | None = None


@dataclass(frozen=True)
class _AccountChoice:
    selection: ComposioAccountSelection
    display_name: str
    is_primary: bool
    account_count: int


def _account_names(record: UserIntegrationDocument) -> str:
    return ", ".join(
        f'"{a.display_name}" ({"expired" if a.status != "connected" else "connected"})'
        for a in record.accounts
    )


async def _choose_account(
    user_id: str | None, tool_name: str, account: str | None
) -> _AccountChoice | DispatchError | None:
    """The connected account a Composio tool call acts as; None leaves the call unpinned.

    Unpinned covers non-Composio tools and integrations with no accounts on
    record, where the tool's own not-connected path (the connect card) answers.
    """
    integration = get_integration_by_tool_slug(tool_name)
    composio_config = integration.composio_config if integration else None
    if integration is None or composio_config is None or not user_id:
        if account:
            return DispatchError(
                kind=DispatchErrorKind.UNKNOWN_ACCOUNT,
                detail=f"'{tool_name}' has no connected accounts to choose between.",
                hint="Retry without `account`.",
            )
        return None
    record = await get_account_record(user_id, integration.id)
    if record is None or not record.accounts:
        return None
    chosen = match_account(record, account) if account else primary_account(record)
    if chosen is None:
        return DispatchError(
            kind=DispatchErrorKind.UNKNOWN_ACCOUNT,
            detail=f"No connected {integration.name} account is called '{account}'.",
            hint=(
                f"If the user meant one of these, pass it as `account`: {_account_names(record)}. "
                "Otherwise ask them which account they meant."
            ),
        )
    live = [a for a in record.accounts if a.status == "connected"]
    if chosen.status != "connected" and live:
        return DispatchError(
            kind=DispatchErrorKind.ACCOUNT_EXPIRED,
            detail=f"The {integration.name} account {chosen.display_name} needs reconnecting.",
            hint=ACCOUNT_NEEDS_RECONNECT_HINT,
        )
    return _AccountChoice(
        selection=ComposioAccountSelection(
            toolkit=composio_config.toolkit, connected_account_id=chosen.connected_account_id
        ),
        display_name=chosen.display_name,
        is_primary=chosen.connected_account_id == record.primary_account_id,
        account_count=len(record.accounts),
    )


def _usage_properties(tool_name: str, choice: _AccountChoice | None) -> dict[str, object]:
    properties: dict[str, object] = {"tool_name": tool_name, "via": "execute"}
    if choice is not None:
        properties["account_count"] = choice.account_count
        properties["account_is_primary"] = choice.is_primary
    return properties


def _with_account(config: RunnableConfig, choice: _AccountChoice | None) -> RunnableConfig:
    if choice is None:
        return config
    metadata = {
        **(config.get("metadata") or {}),
        "composio_account": choice.selection.model_dump(mode="json"),
    }
    return {**config, "metadata": metadata}


class _TicketData(TypedDict, total=False):
    """A ticket operation's data as the model sent it; unvalidated, hence object."""

    id: object


def dispatch_config_for(user_id: str) -> RunnableConfig:
    """Run config carrying the caller's identity for user-bound wrappers.

    Tools are user-agnostic at resolve time (see the resolver's materialized
    cache); Composio/MCP wrappers resolve per-user auth from config at
    invocation — ``configurable`` AND ``metadata``, both, because different
    wrappers read different keys. One helper so synthesized configs (sandbox
    route, ledger executor) cannot drift into setting only one and running
    as Composio's "default" user with no connected accounts.
    """
    return {
        "configurable": {"user_id": user_id},
        "metadata": {"user_id": user_id},
    }


@dataclass(frozen=True)
class ToolSpace:
    """What one caller may reach through the proxy.

    integration_only is the sandbox route's scope: internal tools need graph
    runtime the route doesn't have, and excluding them narrows what a leaked
    token can reach. tool_names is a subagent's complete legitimate space (its
    toolkit, its MCP tools, the internals); any resolved tool outside it is
    refused, so a scoped subagent cannot reach another integration on demand.
    None is the executor's space: the whole registry.
    """

    integration_only: bool = False
    tool_names: Container[str] | None = None


def _refusal(resolved: ResolvedTool, space: ToolSpace) -> DispatchError | None:
    if space.integration_only and not resolved.is_integration:
        log.warning(
            f"{LogTag.TOOL} execute: internal tool refused on integration-only surface",
            tool_name=resolved.name,
        )
        return DispatchError(
            kind=DispatchErrorKind.INTERNAL_TOOL,
            detail=f"'{resolved.name}' is an internal tool, not an integration tool.",
            hint=(
                "Sandbox scripts can only call integration tools (Gmail, GitHub, "
                "Notion, MCP, ...). Use internal tools from the conversation instead."
            ),
        )
    if space.tool_names is not None and resolved.name not in space.tool_names:
        log.warning(
            f"{LogTag.TOOL} execute: tool refused outside the calling agent's tool space",
            tool_name=resolved.name,
        )
        return DispatchError(
            kind=DispatchErrorKind.OUT_OF_SCOPE,
            detail=f"'{resolved.name}' is not available inside this subagent.",
            hint=(
                "It belongs to the main executor, not this subagent. Do not retry it; "
                "finish your task here and let the executor handle it."
            ),
        )
    return None


async def _admit(
    user_id: str | None,
    resolved: ResolvedTool,
    data: dict[str, object],
    account: str | None,
    space: ToolSpace,
) -> tuple[dict[str, object], _AccountChoice | None] | DispatchError:
    """Return the validated args and the account to act as, or why the call may not run."""
    refusal = _refusal(resolved, space)
    if refusal is not None:
        return refusal
    validated = _validate_args(resolved.tool, data)
    if isinstance(validated, DispatchError):
        log.warning(
            f"{LogTag.TOOL} execute: args failed schema validation", tool_name=resolved.name
        )
        return validated
    choice = await _choose_account(user_id, resolved.name, account)
    if isinstance(choice, DispatchError):
        log.warning(f"{LogTag.TOOL} execute: account not usable", tool_name=resolved.name)
        return choice
    return validated, choice


async def dispatch_tool(
    *,
    user_id: str | None,
    tool_name: str,
    data: dict[str, object],
    config: RunnableConfig,
    account: str | None = None,
    space: ToolSpace | None = None,
) -> ToolExecutionResult:
    """Run one proxied tool, as the named connected account (the primary when None).

    space is the caller's reach (see ToolSpace); None is the executor's whole registry.
    """
    space = space or ToolSpace()
    if tool_name in TICKET_NAMES:
        if space.integration_only:
            # Tickets need a conversation (owner/caller checks) the sandbox
            # route deliberately withholds: without it every ticket call
            # misses, so refuse loudly instead of failing silently downstream.
            log.warning(
                f"{LogTag.TOOL} execute: ticket operation refused on integration-only surface",
                tool_name=tool_name,
            )
            return _failure(
                user_id,
                tool_name,
                DispatchError(
                    kind=DispatchErrorKind.INTERNAL_TOOL,
                    detail=f"'{tool_name}' is a conversation ticket, not an integration tool.",
                    hint="Approve, revoke, and redeem only from the conversation, never from a sandbox script.",
                ),
            )
        return await _dispatch_ticket(
            user_id=user_id,
            tool_name=tool_name,
            data=data,
            config=config,
        )
    resolved = await resolve_tool(user_id, tool_name)
    if resolved is None:
        log.warning(f"{LogTag.TOOL} execute: unknown tool", tool_name=tool_name)
        return _failure(
            user_id,
            tool_name,
            DispatchError(
                kind=DispatchErrorKind.UNKNOWN_TOOL,
                detail=f"Unknown tool '{tool_name}'.",
                hint=(
                    "The name must be an exact tool name. Discover tools with "
                    "retrieve_tools(query=...) and use the name it returns verbatim."
                ),
            ),
        )
    resolved_name, tool = resolved.name, resolved.tool
    admitted = await _admit(user_id, resolved, data, account, space)
    if isinstance(admitted, DispatchError):
        return _failure(user_id, resolved_name, admitted)
    validated, choice = admitted

    # Named before the run so a propagated infrastructure failure still says
    # which tool it was; the ok outcome is stamped only once the invoke has
    # actually returned.
    log.set_ns("execute", tool=resolved_name)
    if choice is not None:
        log.set_ns(
            "execute",
            connected_account_id=choice.selection.connected_account_id,
            account_is_primary=choice.is_primary,
        )
    # Long-running orchestration tools manage their own lifecycles — the same
    # exemption the in-graph node applies, read from the same constant so a
    # proxied call is never bounded more tightly than a direct one.
    bound = None if resolved_name in TOOL_TIMEOUT_EXEMPT_TOOLS else TOOL_EXECUTION_TIMEOUT_SECONDS
    try:
        async with asyncio.timeout(bound):
            output = await tool.ainvoke(validated, config=_with_account(config, choice))
    except TimeoutError:
        # The only failure whose effect is unknown — the provider may have
        # applied it after we stopped waiting. Bounded here so the model gets
        # this structured error; see TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS.
        return _failure(
            user_id,
            resolved_name,
            DispatchError(
                kind=DispatchErrorKind.TIMEOUT,
                detail=(
                    f"'{resolved_name}' did not return within {TOOL_EXECUTION_TIMEOUT_SECONDS}s."
                ),
                hint=(
                    "The operation may or may not have completed on the provider side. "
                    "Verify its effect before retrying — an identical retry can duplicate it."
                ),
            ),
        )
    log.set_ns("execute", outcome="ok")

    if resolved.is_integration:
        # Observed-shape learning rides every real response; fire-and-forget so
        # it can never slow or fail the dispatch it learns from.
        spawn_logged_task(
            "record_tool_output_shape",
            record_observed_shape(resolved_name, output, scope=resolved.shape_scope),
            tool_name=resolved_name,
        )

    _EXECUTE_DISPATCH_TOTAL.labels(outcome="ok").inc()
    if user_id:
        # The one TOOL_USED per proxied run, attributed to the real tool with
        # via="execute" (the middleware emitter skips calls named execute for
        # this reason: one action, one event, one emitter).
        capture_event(user_id, AnalyticsEvents.TOOL_USED, _usage_properties(resolved_name, choice))

    account = choice.display_name if choice is not None and choice.account_count > 1 else None
    return ToolExecutionResult(ok=True, resolved_name=resolved_name, output=output, account=account)


async def _dispatch_ticket(
    *,
    user_id: str | None,
    tool_name: str,
    data: dict[str, object],
    config: RunnableConfig,
) -> ToolExecutionResult:
    """Honor a ticket operation (approve/revoke) on a ledger row.

    Runs BEFORE resolution: ticket names are control-plane, not provider
    tools, so they bypass the registry, the catalog, and the caller's tool
    space. Enforcement lives at the row (owner-or-executor, conversation and
    user match) — the same checks the old revoke_tool applied. Refusals are
    answers, not failures: they return ``ok=True`` with the refusal as the
    output, so the model reads them instead of tripping the failure metric.
    """
    from app.services.hil.ledger_decide import (  # noqa: PLC0415 -- ledger_decide reaches the registry via dispatch; a top-level import closes that cycle
        redeem_approved,
        revoke_ticket,
    )

    configurable: AgentConfigurable = agent_configurable(config)
    caller = str(configurable.get("thread_id") or "")
    ticket_user = str(configurable.get("user_id") or user_id or "")
    conversation_id = str(configurable.get("conversation_id") or "")
    ticket: _TicketData = cast(_TicketData, data)
    approval_id = ticket.get("id")
    if not isinstance(approval_id, str) or not approval_id:
        return ToolExecutionResult(
            ok=True,
            resolved_name=tool_name,
            output=f'Name the ticket: {tool_name} needs data {{"id": "<approval_id>"}}.',
        )
    if tool_name == TICKET_APPROVE_NAME:
        result = await redeem_approved(
            approval_id,
            user_id=ticket_user,
            conversation_id=conversation_id,
            caller=caller,
        )
        text = (
            f"Executed '{approval_id}' ({result.state.value}): {result.detail}"
            if result.ok
            else f"Could not run '{approval_id}': {result.detail}"
        )
    elif tool_name == TICKET_REVOKE_NAME:
        text = await revoke_ticket(
            approval_id,
            user_id=ticket_user,
            conversation_id=conversation_id,
            caller=caller,
        )
    else:
        # Unreachable: dispatch_tool only routes TICKET_NAMES here. Loud if
        # that ever changes, so a new ticket name cannot fall through silent.
        raise ValueError(f"Unknown ticket operation '{tool_name}'.")
    _EXECUTE_DISPATCH_TOTAL.labels(outcome="ok").inc()
    return ToolExecutionResult(ok=True, resolved_name=tool_name, output=text)


def _failure(user_id: str | None, tool_name: str, error: DispatchError) -> ToolExecutionResult:
    """A predictable dispatch failure — counted, captured, then returned.

    Failure is its own event, never a missing one: retries-per-success is only
    computable if the numerator is recorded as reliably as the denominator.
    """
    _EXECUTE_DISPATCH_TOTAL.labels(outcome=str(error.kind)).inc()
    log.set_ns("execute", tool=tool_name, outcome=str(error.kind))
    if user_id:
        capture_event(
            user_id,
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": tool_name, "reason": str(error.kind)},
        )
    return ToolExecutionResult(ok=False, resolved_name=tool_name, error=error)


def _validate_args(tool: BaseTool, data: dict[str, object]) -> dict[str, object] | DispatchError:
    """``data`` coerced through the tool's schema, or the correction to return.

    Provider-side constrained decoding is gone under the proxy — this check is
    what stands in for it, so it fails loud with the exact Pydantic errors.
    """
    schema = tool.args_schema
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        # Dict-style JSON schemas (some MCP adapters) have no Pydantic model to
        # coerce through; the tool's own run performs its validation.
        return data
    try:
        model = schema.model_validate(data)
    except ValidationError as e:
        return DispatchError(
            kind=DispatchErrorKind.INVALID_ARGS,
            detail=json.dumps(e.errors(include_url=False), default=str),
            hint=f"Fix `data` to match the {tool.name} schema shown by retrieve_tools, then retry.",
        )
    # exclude_unset so tool-side defaults stay the tool's own — mirrors the
    # bind path, which forwards only the args the model actually supplied.
    return model.model_dump(mode="json", exclude_unset=True)
