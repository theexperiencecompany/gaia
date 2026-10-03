"""Fixed prompt text the context sections inject, and the separators joining them.

Separated from the sections that place it so a wording change is a diff a
reviewer can read without also reading the fetch logic around it.
"""

from typing import Final, NamedTuple

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
    "   - Your output is consumed by the system, not a human. Be terse and action-only."
)

#: Comms: pure capability awareness — it delegates via call_executor rather
#: than acting.
CONNECTED_INTEGRATIONS_HEADER = (
    "Connected integrations (the executor can act on these when you delegate via call_executor):"
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
