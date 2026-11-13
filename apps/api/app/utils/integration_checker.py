"""Surfacing an integration the user has to (re)connect, and the agent copy for it.

The card and the copy are one operation, never two: the copy tells the agent
exactly what the user was sent, so anything that produces it must also produce
the card.

A UI client renders the card with its own connect flow. Everywhere else the card
carries the link itself (a single-use connect link, an MCP provider's
authorization URL, or the integrations page when neither exists) and the bot or
the result delivery sends it as a button, so no link depends on the model
copying it. The agent is told the link either way: it must know what the user
can see. A background run has nobody present to act, so its card is delivered
with the run's result and the agent records the gap and carries on.
"""

from typing import Literal, NamedTuple

from app.agents.tools.run_record import block_integration
from app.constants.auth import CONNECT_LINK_TTL_MINUTES
from app.constants.cache import OAUTH_STATE_TTL
from app.constants.chat import INTEGRATION_CONNECTION_TOOL_NAME
from app.constants.integrations import (
    ACCOUNT_NEEDS_RECONNECT_HINT,
    MANAGED_BY_MCP,
    ConnectMode,
)
from app.db.repositories.user_integrations import user_integration_repository
from app.helpers.mcp_helpers import get_mcp_oauth_redirect_uri
from app.models.agent_models import (
    AgentConfigurableView,
    current_run_config,
    current_stream_writer,
    read_agent_configurable,
)
from app.models.chat_models import SourceCategory
from app.models.integration_models import IntegrationAccount
from app.services.connect_link_service import build_connect_link_url, integrations_page_url
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.mcp_oauth import build_oauth_auth_url
from shared.py.wide_events import log


class _StandaloneAuth(NamedTuple):
    """Whether an MCP integration can hand the model a provider OAuth URL, and what it is."""

    kind: Literal["oauth", "token_only", "unavailable", "not_mcp"]
    url: str | None = None


async def _standalone_mcp_auth(
    user_id: str, integration_id: str, *, build_url: bool
) -> _StandaloneAuth:
    """Build the provider authorization URL for an OAuth MCP integration, or say why not.

    Only MCP has one. A bearer server has no OAuth endpoint, so callers must never
    offer it a login link. build_url=False classifies without paying for OAuth
    discovery, which a background run cannot use.
    """
    try:
        resolved = await IntegrationResolver.resolve(integration_id)
        if resolved is None or resolved.managed_by != MANAGED_BY_MCP or resolved.mcp_config is None:
            return _StandaloneAuth(kind="not_mcp")
        if resolved.auth_type == "bearer":
            return _StandaloneAuth(kind="token_only")
        if not resolved.requires_auth:
            return _StandaloneAuth(kind="not_mcp")
        if not build_url:
            return _StandaloneAuth(kind="oauth")

        mcp_client = await get_mcp_client(user_id=user_id)
        auth_url = await build_oauth_auth_url(
            mcp_client.token_store,
            integration_id=integration_id,
            redirect_uri=get_mcp_oauth_redirect_uri(),
            redirect_path="/integrations",
        )
        return _StandaloneAuth(kind="oauth", url=auth_url)
    except Exception as e:
        log.warning(
            "MCP standalone authorization URL unavailable",
            integration_id=integration_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return _StandaloneAuth(kind="unavailable")


class _Ask(NamedTuple):
    """What the user is asked to do, as the card says it and as the agent is told."""

    card: str
    lead: str
    verb: str
    gap: str
    button: str


def _ask(mode: ConnectMode, expired: bool, name: str, account: str | None) -> _Ask:
    if account is not None:
        return _Ask(
            card=f"Your {name} account {account} lost its connection. Sign in as {account} "
            "again to keep using it.",
            lead=f"The user's {name} account {account} lost its connection and must be signed "
            f"in again. {ACCOUNT_NEEDS_RECONNECT_HINT}",
            verb="reconnect",
            gap=f"the {name} account {account} lost its connection",
            button="reconnect button",
        )
    if mode is ConnectMode.ADD_ACCOUNT:
        return _Ask(
            card=f"Add another {name} account. Sign in with the account you want to add.",
            lead=f"The user wants to add another {name} account; their current accounts stay "
            "connected.",
            verb="add another account to",
            gap=f"another {name} account was not added",
            button="button to add the account",
        )
    if mode is ConnectMode.RECONNECT and not expired:
        return _Ask(
            card=f"Your {name} connection needs fresh authorization. Reauthorize to keep using it.",
            lead=f"The user's {name} connection needs fresh authorization; they need to "
            "reconnect to refresh access.",
            verb="reconnect",
            gap=f"the {name} connection needs a refresh",
            button="reconnect button",
        )
    if expired:
        return _Ask(
            card=f"Your {name} connection expired. Sign in again to keep using it.",
            lead=f"The user's {name} connection EXPIRED. They had it connected and the "
            f"access has since died, so they must sign in again. Do NOT tell them to connect "
            f"{name} for the first time.",
            verb="reconnect",
            gap=f"the {name} connection expired",
            button="reconnect button",
        )
    return _Ask(
        card=f"To use {name} features, please connect your account first.",
        lead=f"{name} needs to be connected.",
        verb="connect",
        gap=f"{name} is not connected",
        button="connect button",
    )


async def _connected_account_names(user_id: str, integration_id: str) -> list[str]:
    """Name the accounts already connected, primary first, for a card adding another."""
    record = await user_integration_repository.get_for_user(user_id, integration_id)
    if record is None:
        return []
    ordered = sorted(record.accounts, key=lambda a: a.id != record.primary_account_id)
    return [a.display_name for a in ordered]


class _Link(NamedTuple):
    """The link a non-UI user is sent, and how long it works (None: the permanent integrations page)."""

    url: str
    valid_minutes: int | None

    def described(self) -> str:
        """Say the link as the agent is told it: the URL and, when it expires, when."""
        if self.valid_minutes is None:
            return f"{self.url} (the integrations page; they must be signed in to GAIA)"
        return f"{self.url} (single use, valid for {self.valid_minutes} minutes)"


class _Prompt(NamedTuple):
    """The facts every channel-specific instruction needs."""

    ask: _Ask
    integration_id: str
    integration_name: str
    user_id: str
    account: IntegrationAccount | None
    auth: _StandaloneAuth
    integrations_url: str


def _stop(prompt: _Prompt) -> str:
    """End the integration's part of the run: the user's tap starts a new turn."""
    return (
        f"Nothing more can be done with {prompt.integration_name} until they do, so do not "
        f"call any {prompt.integration_name} tool again this run; finish the rest of the task "
        "and say what is waiting on them."
    )


async def _user_link(prompt: _Prompt) -> _Link:
    """Mint the link a non-UI user (re)connects with.

    An OAuth MCP integration's provider URL when one was built; the integrations
    page for an API-key server, a provider whose discovery failed, or when no
    link can be minted (Redis down); otherwise a single-use connect link.
    """
    integrations_page = _Link(prompt.integrations_url, None)
    if prompt.auth.kind == "oauth" and prompt.auth.url:
        return _Link(prompt.auth.url, OAUTH_STATE_TTL // 60)
    if prompt.auth.kind in ("token_only", "unavailable"):
        return integrations_page
    connect_url = await build_connect_link_url(
        prompt.user_id, prompt.integration_id, prompt.account.id if prompt.account else None
    )
    return _Link(connect_url, CONNECT_LINK_TTL_MINUTES) if connect_url else integrations_page


def _what_to_do_there(prompt: _Prompt) -> str:
    """Say what the user does on the page the link opens."""
    if prompt.auth.kind == "token_only":
        return f"enter the API key there to {prompt.ask.verb} {prompt.integration_name}"
    return f"{prompt.ask.verb} {prompt.integration_name} there"


def _auth_note(prompt: _Prompt) -> str:
    """Why the link is the integrations page, when the integration has no sign-in link."""
    if prompt.auth.kind == "token_only":
        return (
            "This integration authenticates with an API key, so no standalone authorization "
            "URL exists. "
        )
    if prompt.auth.kind == "unavailable":
        return "No standalone authorization URL is available for this integration right now. "
    return ""


def _background_link(prompt: _Prompt) -> _Link | None:
    """Return the link a background card carries; None when one is minted as the result is sent.

    A single-use link dies within the hour and a background result is read later,
    so it is minted at delivery (app.services.bot.cards), never here. Only the
    permanent integrations page is fixed now, for integrations with no sign-in link.
    """
    if prompt.auth.kind in ("token_only", "unavailable"):
        return _Link(prompt.integrations_url, None)
    return None


def _background_message(prompt: _Prompt, link: _Link | None) -> str:
    """Record the gap and carry on: nobody is present, so the card travels with the result."""
    ask = prompt.ask
    target = (
        f"linking to {link.described()}"
        if link is not None
        else "whose single-use sign-in link is minted fresh when the result is sent (if it has "
        f"expired by the time they open it, they can {ask.verb} it at {prompt.integrations_url})"
    )
    return (
        f"{ask.lead} {_auth_note(prompt)}This is a background run and no user is present to "
        f"{ask.verb} it now, so retrying {prompt.integration_name} this run cannot succeed. A "
        f"{ask.button} {target} is attached to this run's result and is delivered to the user "
        f"with it; they {_what_to_do_there(prompt)}. Record in your result that {ask.gap} and "
        "that the button is attached, then carry on with the rest of the task."
    )


def _ui_message(prompt: _Prompt) -> str:
    """Point at the card a UI client renders, relaying any standalone URL, and end the integration's part of the run."""
    ask = prompt.ask
    stop = _stop(prompt)
    if prompt.auth.kind == "oauth" and prompt.auth.url:
        return (
            f"{ask.lead} A {ask.button} has been shown to the user, and a standalone "
            f"authorization URL is available: {prompt.auth.url}. Relay that URL verbatim as a "
            f"clickable link so the user can {ask.verb} even if the card is not visible. {stop}"
        )
    if prompt.auth.kind == "token_only":
        return (
            f"{ask.lead} This integration authenticates with an API key, so no standalone "
            f"authorization URL exists. A {ask.button} has been shown to the user; ask "
            f"them to enter the API key there. {stop}"
        )
    if prompt.auth.kind == "unavailable":
        return (
            f"{ask.lead} A {ask.button} has been shown to the user, but no standalone "
            f"authorization URL is available right now. Ask the user to click it. {stop}"
        )
    return (
        f"{ask.lead} A {ask.button} has been shown to the user, so do NOT include any URL in "
        f"your reply, the UI card handles it. Ask the user to click it. {stop}"
    )


def _messaging_app_message(prompt: _Prompt, link: _Link) -> str:
    """Tell the agent the button the user was sent on a messaging app, link included."""
    ask = prompt.ask
    return (
        f"{ask.lead} {_auth_note(prompt)}The user is on a messaging app. The system has sent "
        f"them a {ask.button} "
        f"as its own message, linking to {link.described()}; they {_what_to_do_there(prompt)}. "
        f"They see it directly, so refer to it in your reply; repeating the link is optional. "
        f"{_stop(prompt)}"
    )


def _already_sent_message(prompt: _Prompt) -> str:
    """Answer a repeat ask in the same run: the card went out on the first ask only."""
    return (
        f"{prompt.ask.lead} The {prompt.ask.button} was already sent to the user earlier in "
        f"this run. {_stop(prompt)}"
    )


async def _block_for_run(run: AgentConfigurableView, integration_id: str) -> bool:
    """Block the integration for the rest of the run; False when the run already asked once.

    invoke_tool refuses a blocked integration's calls, so the stop the agent is told
    about does not depend on the model obeying it.
    """
    if not run.stream_id:
        return True
    return await block_integration(run.stream_id, integration_id)


async def request_integration_connection(
    integration_id: str,
    integration_name: str,
    user_id: str,
    *,
    mode: ConnectMode = ConnectMode.CONNECT,
    account: IntegrationAccount | None = None,
) -> str:
    """Show the connect card for mode and return the agent instruction.

    An OAuth MCP integration also yields its standalone provider URL; a token-only
    MCP server is reported as having none. Everything else keeps the connect-link
    or the integrations page. A background run gets the integrations page and
    carries on.
    """
    # Only Composio grants ever reach the ``expired`` status, so MCP integrations
    # fall through to the never-connected wording without needing a special case.
    expired = await user_integration_repository.is_expired(user_id, integration_id)
    ask = _ask(mode, expired, integration_name, account.display_name if account else None)
    run = read_agent_configurable(current_run_config())
    source_category = run.source_category
    adding = mode is ConnectMode.ADD_ACCOUNT
    first_ask = await _block_for_run(run, integration_id) if not adding else True
    background = run.execution_mode == "background"
    on_ui = source_category == SourceCategory.UI.value

    # Login-required but permanent: the fallback when no single-use link applies.
    integrations_url = integrations_page_url()
    # A background run delivers its result after this, past an MCP OAuth state's
    # lifetime, so it never pays for building one.
    auth = await _standalone_mcp_auth(user_id, integration_id, build_url=not background)
    prompt = _Prompt(
        ask=ask,
        integration_id=integration_id,
        integration_name=integration_name,
        user_id=user_id,
        account=account,
        auth=auth,
        integrations_url=integrations_url,
    )

    if not first_ask and not on_ui:
        return _already_sent_message(prompt)
    # The UI card runs its own connect flow; everywhere else the card carries the link.
    messaging_link = None if on_ui or background else await _user_link(prompt)
    link = _background_link(prompt) if background else messaging_link

    # None means no runnable context at all (e.g. the dev direct-invocation
    # endpoints), so there is no stream for a card to travel on. A run shows
    # one card per integration however many calls hit the gap.
    if source_category is not None and first_ask:
        current_stream_writer()(
            {
                INTEGRATION_CONNECTION_TOOL_NAME: {
                    "integration_id": integration_id,
                    "integration_name": integration_name,
                    "expired": not adding
                    and (expired or mode is ConnectMode.RECONNECT or account is not None),
                    "add_account": adding,
                    "message": ask.card,
                    "connected_accounts": (
                        await _connected_account_names(user_id, integration_id) if adding else []
                    ),
                    "reconnect_account": (
                        {"id": account.id, "name": account.display_name} if account else None
                    ),
                    # An API-key server is connected by pasting a secret; a bot card
                    # must send the user to GAIA for that, never ask in chat.
                    "needs_api_key": auth.kind == "token_only",
                    "connect_url": link.url if link else None,
                    "connect_url_valid_minutes": link.valid_minutes if link else None,
                }
            }
        )

    if messaging_link is not None:
        return _messaging_app_message(prompt, messaging_link)
    if background:
        return _background_message(prompt, link)
    return _ui_message(prompt)
