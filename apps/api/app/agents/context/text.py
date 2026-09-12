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
    "   - Just execute. If you need a decision you cannot make, write the question into "
    "the Context section of the active todo's canvas.md and stop.\n"
    "   - Your output is consumed by the system, not a human. Be terse and action-only."
)

#: Comms: pure capability awareness — it hands off rather than acting.
CONNECTED_INTEGRATIONS_HEADER = (
    "Connected integrations (hand off to the matching subagent to use them):"
)

#: The executor performs the handoffs, so its header states that the list is
#: live, names the parenthesised id as the handoff ``subagent_id``, and guards
#: against reading always-available built-ins as "not connected" just because
#: they are absent from the list.
EXECUTOR_CONNECTED_INTEGRATIONS_HEADER = (
    "CONNECTED INTEGRATIONS (live snapshot of the user's currently connected accounts as of "
    "this turn; this is the latest connected set, so trust it over retrieve_tools for what is "
    "connected). To act on one, handoff to its subagent using the id in parentheses as the "
    "handoff subagent_id. If the user asks for a provider that is NOT listed here, STILL do the "
    "handoff: the handoff is what shows the user the connect card. Telling the user to connect "
    "WITHOUT handing off leaves them hunting for a button that was never rendered. Built-in "
    "subagents (todos, gaia_knowledge_guide, docgen) are always available; one is "
    "listed below only where a connected account could be mistaken for it:"
)

#: Comms: knows a device exists so it delegates local/file work rather than
#: guessing. It never touches files itself.
CONNECTED_DEVICES_HEADER = (
    "Connected devices (the user's own machines). For anything about the user's local "
    "files, folders, apps, or computer, delegate to the executor:"
)

#: Executor: the crucial nudge. The device's files live on the user's real
#: machine, reachable through the device's tools; the sandbox is a cloud
#: container that CANNOT see them. This is what stops the executor from
#: answering "what's in my downloads" by running `ls` in the sandbox.
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
    """A built-in subagent whose job a connected provider gets mistaken for."""

    subagent_id: str
    description: str
    provider_ids: frozenset[str]


#: Built-ins the manifest must spell out when one of these providers is connected.
#: Left implicit, the built-in appears nowhere in the list and the agent reads "the
#: user's todo list" as whichever task product it can see — which is how an executor
#: filed eight GAIA todos as "8 tasks created (Todoist)".
BUILTIN_CAPABILITY_OVERLAPS: Final[tuple[BuiltinOverlap, ...]] = (
    BuiltinOverlap(
        subagent_id="todos",
        description="Todos: GAIA's own todo list",
        provider_ids=frozenset({"todoist", "googletasks"}),
    ),
)

#: Renders to ``- Todos: GAIA's own todo list, not Todoist (todos)``.
BUILTIN_OVERLAP_LINE: Final[str] = "- {description}, not {providers} ({subagent_id})"

MEMORY_RECALL_HEADER = (
    "Based on our previous conversations (bracketed dates say when "
    "something happened / was last mentioned):"
)

CORE_MEMORY_HEADER = "What you remember about this user (memory core):"

GAIA_KNOWLEDGE_HEADER = "About Gaia (your identity and capabilities):"

#: Tells the model its view is partial when the volatile block overruns the
#: ceiling in ``assemble``. Fixed text, so the notice does not itself grow with
#: the content it stands in for.
VOLATILE_BLOCK_TRUNC_MARKER = "\n…[context truncated to bound prompt size]…\n"
