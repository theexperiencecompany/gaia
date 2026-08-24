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
    "the active todo's canvas (Context section) and stop.\n"
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
    "subagents (reminders, todos, gaia_knowledge_guide, docgen) are always available; one is "
    "listed below only where a connected account could be mistaken for it:"
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
