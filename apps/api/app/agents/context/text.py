"""Fixed prompt text the context sections inject, and the separators joining them.

Separated from the sections that place it so a wording change is a diff a
reviewer can read without also reading the fetch logic around it.
"""

from typing import Final, NamedTuple

from app.constants.execute import RAN_AS_ACCOUNT_KEY
from app.constants.integrations import (
    CONNECT_INTEGRATION_TOOL,
    DISCONNECT_INTEGRATION_TOOL,
    RENAME_INTEGRATION_ACCOUNT_TOOL,
    SET_PRIMARY_INTEGRATION_ACCOUNT_TOOL,
    ConnectMode,
)

#: Sections within the stable block are single lines or short line groups, so
#: they read as one block. Volatile sections are paragraphs and get a blank line.
STABLE_SECTION_JOIN = "\n"
VOLATILE_SECTION_JOIN = "\n\n"

BACKGROUND_EXECUTION_BANNER = (
    "🤖 BACKGROUND EXECUTION (no human is reading this turn)\n"
    "   - You were woken by a scheduled trigger. There is no user to ask.\n"
    "   - Do NOT ask clarifying questions, present plans for approval, or seek confirmation.\n"
    '   - Do NOT produce conversational acknowledgements ("Sure, I\'ll…", "Let me know if…").\n'
    "   - Gated actions register persistent approval cards (never expire) instead of "
    "pausing: if a call comes back PENDING, leave it and move on to independent work "
    "or stop — the user decides in the Approvals tab and durable work resumes. "
    "If the step is not needed, withdraw it with a revoke before the run ends.\n"
    "   - Just execute. If no card can carry the decision (a truly novel choice with "
    "no standing instruction), write the question into "
    "the Context section of the active todo's canvas.md and stop.\n"
    "   - If an integration the task needs is not connected, nobody can connect it during "
    "this run: do not retry it or search for its tools again. Record it as not connected "
    "in your result and carry on with the rest of the task.\n"
    "   - Your output is consumed by the system, not a human. Be terse and action-only."
)

#: Comms: pure capability awareness — it delegates via call_executor rather
#: than acting.
CONNECTED_INTEGRATIONS_HEADER = (
    "Connected integrations (the executor can act on these when you delegate via "
    "call_executor). Each can hold several accounts. If they ask to connect one already "
    "listed here, tell them which accounts it has and ask whether they want to add another; "
    'when they clearly want another, delegate it ("add another Gmail account"):'
)

#: Comms: knows a device exists so it delegates local/file work rather than
#: guessing. It never touches files itself.
CONNECTED_DEVICES_HEADER = (
    "Connected devices (the user's own machines). For anything about the user's local "
    "files, folders, apps, or computer, delegate to the executor:"
)

#: The device's files live on the user's real machine; the sandbox is a cloud
#: container that CANNOT see them. Stops the executor answering "what's in my
#: downloads" by running ls in the sandbox.
EXECUTOR_CONNECTED_DEVICES_HEADER = (
    "CONNECTED DEVICES (the user's own machines). To read, change, or run anything on the "
    "user's machine, use run_on_device(device_id, command) - pass the id shown in each line "
    "below VERBATIM as device_id (never the name). Its shell runs on the user's real machine; "
    "the sandbox shell is a cloud container that CANNOT see it, so NEVER answer a question "
    "about the user's own files or apps by running commands in the sandbox. A device may also "
    "expose its own MCP servers (listed after 'exposing:' on each line); to use one, work "
    "through that server's own tools - retrieve them and hand off to its subagent - rather "
    "than run_on_device. Use list_devices for live online status and the MCP servers a device "
    "exposes:"
)


class BuiltinOverlap(NamedTuple):
    """A built-in capability whose job a connected provider gets mistaken for."""

    subagent_id: str
    description: str
    provider_ids: frozenset[str]


#: Built-ins the manifest must spell out when one of these providers is
#: connected — left implicit, an executor once filed 8 GAIA todos as
#: "8 tasks created (Todoist)".
BUILTIN_CAPABILITY_OVERLAPS: Final[tuple[BuiltinOverlap, ...]] = (
    BuiltinOverlap(
        subagent_id="todos",
        description="Todos: GAIA's own todo list",
        provider_ids=frozenset({"todoist", "googletasks"}),
    ),
)

#: Renders to ``- Todos: GAIA's own todo list, not Todoist (todos)``.
BUILTIN_OVERLAP_LINE: Final[str] = "- {description}, not {providers} ({subagent_id})"

#: The activation variant of the header above. Same guarantee (call the tool even
#: for an unlisted integration, because the call is what renders the connect card),
#: but the executor acts on the integration itself instead of routing to a subagent.
EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER = (
    "CONNECTED INTEGRATIONS (live snapshot of the user's currently connected accounts as of "
    "this turn; this is the latest connected set, so trust it over retrieve_tools for what is "
    "connected). To act on one, call activate_integration with the id in parentheses, then use "
    "its tools yourself. If the user asks for an integration that is NOT listed here, STILL "
    "call activate_integration on it: that call is what shows the user the connect card. "
    "Telling the user to connect WITHOUT calling it leaves them hunting for a button that was "
    "never rendered. Built-in integrations (reminders, todos, gaia_knowledge_guide, docgen) "
    "are always available and are not listed here:"
)

#: Shown wherever an integration's accounts are listed.
MULTI_ACCOUNT_INSTRUCTION: Final[str] = (
    "GAIA supports several accounts per integration; the accounts listed above are live and "
    "win over anything remembered, so a listed account never needs connecting again. Tools act "
    "as the default account unless you pass `account` to execute (an id or a name). If the user names "
    "an account, or it is clear which one they mean, use only that one. A request that names "
    "or describes no account ('my latest email', 'what is on today') could be in any of them: "
    "call the tool for every connected account at once, as parallel calls in one "
    "turn, and say which result came from which; never answer it from the default alone. For a write with no account named, use "
    "the default. Answers, summaries and anything you set up to track cover every account "
    "unless the user narrowed it. When the user describes an account instead of naming it "
    "('my work email', 'my school calendar'), that is not an unnamed read: before calling "
    "any tool, decide which account they mean from what each one reveals: its "
    "address or workspace, its nickname, and what you remember about how the user uses it. The "
    "default is only what a call that names no account uses; it says nothing about what an "
    "account is for. If one account clearly fits, use it and say which. If several could, "
    "or none does, ask in one short question that lists them, and offer to connect another "
    f"({CONNECT_INTEGRATION_TOOL} mode='{ConnectMode.ADD_ACCOUNT}'); once the user answers, "
    f"name that account to match ({RENAME_INTEGRATION_ACCOUNT_TOOL}) and save it with "
    "add_memory, so you never ask again. Check each result's "
    f"{RAN_AS_ACCOUNT_KEY} is the account you meant. If the named account fails, tell the "
    "user; never use another in its place. Reconnect an expired account with "
    f"{CONNECT_INTEGRATION_TOOL} mode='{ConnectMode.RECONNECT}' and that account, add one "
    f"with mode='{ConnectMode.ADD_ACCOUNT}', remove one with {DISCONNECT_INTEGRATION_TOOL}, "
    f"change the default with {SET_PRIMARY_INTEGRATION_ACCOUNT_TOOL}. Rename a generic account "
    f"({RENAME_INTEGRATION_ACCOUNT_TOOL}) once you learn whose it is, and save how the user "
    "uses each account with add_memory."
)

#: The comms agent sees the same account lists but acts on none of them.
COMMS_MULTI_ACCOUNT_NOTE: Final[str] = (
    "GAIA supports several accounts per integration; the accounts listed above are live and "
    "win over anything remembered, so never tell the executor a listed account needs "
    "connecting. Using, renaming or managing them is executor work: delegate it, and never "
    "acknowledge a rename yourself. Pass on only what the user said about accounts in this "
    "message: if they named none, neither does your task (write 'their Gmail', never an "
    "address), and it never steers the executor away from an account, even one you remember "
    "failing; an earlier request or agenda item never names one. Pass remembered usage "
    "patterns as context, not limits, and save what the user says an account is for with "
    "add_memory. When you report, cover every account the executor used, name the account "
    "each result came from as listed (never 'the other account'), and never describe a step "
    "it did not report. When the user describes an account by what it is for ('my school "
    "email'), pass their words on as they said them; the executor picks the account that fits "
    "or asks."
)

#: Activation runs once per conversation, so it points at the per-turn list
#: instead of copying accounts that can change before the next turn.
ACTIVATION_MULTI_ACCOUNT_POINTER: Final[str] = (
    "The user has several {integration} accounts, listed with {integration} in the connected "
    "integrations section. When one has a generic name and you learn whose it is, rename it "
    f"({RENAME_INTEGRATION_ACCOUNT_TOOL}) so later calls never mix them up."
)

#: What every block of remembered history says about itself. A memory of the
#: same login once answered "log me in" in place of the browser.
MEMORY_IS_PAST_NOTE = (
    "These are records of the past. They can answer questions about remembered facts, but "
    "never show that something asked for now has been done, or that live state (what a page, "
    "inbox or account shows now) is still current."
)

MEMORY_RECALL_HEADER = (
    "From our previous conversations (bracketed dates say when "
    f"something happened / was last mentioned). {MEMORY_IS_PAST_NOTE}"
)

CORE_MEMORY_HEADER = "What you remember about this user (memory core):"

GAIA_KNOWLEDGE_HEADER = "About Gaia (your identity and capabilities):"

#: Tells the model its view is partial when the volatile block overruns the
#: ceiling in ``assemble``. Fixed text, so the notice does not itself grow with
#: the content it stands in for.
VOLATILE_BLOCK_TRUNC_MARKER = "\n…[context truncated to bound prompt size]…\n"
