"""The executor prompt doctrine: integrations are activated in-context.

The executor's doctrine: there is no handoff and no per-integration subagent, so every passage that teaches "hand this to the
gmail subagent" has to teach "activate gmail, then do the work yourself".

This rewrites those passages rather than forking the prompt. Two copies of a
450-line prompt drift, and the copy people actually tune would be the other one,
so the executor under the experiment would quietly fall behind on every prompt
fix that lands.

Every rewrite is anchored to text in EXECUTOR_AGENT_PROMPT. A stale anchor skips
that one rewrite with a warning and the rest still apply: this builder runs at
import time, so raising would keep the whole API from starting over one edited
sentence. tests/unit/agents/prompts/test_executor_activation_prompt.py pins every
anchor and replacement, so a skipped rewrite still fails loudly in CI.
"""

from app.agents.prompts.comms_prompts import EXECUTOR_AGENT_PROMPT
from shared.py.wide_events import log

#: (anchor, replacement). Anchors are the smallest distinctive slice of the
#: passage, so ordinary edits elsewhere in the prompt do not break the swap.
_PHRASE_REWRITES: tuple[tuple[str, str], ...] = (
    (
        "TODO (handoff to subagent:todos)",
        'TODO (activate_integration("todos"), then act)',
    ),
    (
        "(create_tracked_todo, a direct tool, no handoff)",
        "(create_tracked_todo, a direct tool, no activation)",
    ),
    (
        "3. act on them yourself or delegate (handoff/spawn_subagent)",
        "3. act on them yourself (bound tools by name, integration tools via execute), "
        "or spawn_subagent to parallelise independent chunks",
    ),
    (
        "→ handoff directly to subagent:gaia_knowledge_guide. Always available, "
        "no retrieve_tools needed.",
        '→ activate_integration("gaia_knowledge_guide"), then answer with its tools. '
        "Always available.",
    ),
    (
        "→ handoff to subagent:docgen. Always available, no retrieve_tools needed.",
        '→ activate_integration("docgen"), then use its tools. Always available.',
    ),
    (
        "(Google Docs/Sheets/Slides, Notion → their own subagents)",
        "(Google Docs/Sheets/Slides, Notion → activate those integrations)",
    ),
    (
        "the task just needs a `read`/`write`/`edit`, a handoff, or another tool",
        "the task just needs a `read`/`write`/`edit`, an activated integration's tool, "
        "or another tool",
    ),
    (
        "- Use these directly (not handoff):",
        "- Use these directly (no activation needed):",
    ),
    # Discovery vocabulary, not delegation: unrewritten it hunts a subagent entry
    # that no longer exists, retrieve_tools returns none, falls back to fetch_webpages.
    # Observed live: a Hacker News request scraped the web instead of activating.
    (
        "there is almost always a dedicated tool or subagent (e.g. subagent:hackernews, "
        "fetch_webpages, web_search_tool) that is better than hand-rolling it. Do NOT curl "
        "an API or scrape a site in bash when a tool/subagent covers it.",
        "there is almost always a dedicated INTEGRATION or tool (e.g. the hackernews "
        "integration, fetch_webpages, web_search_tool) that is better than hand-rolling it. "
        "When retrieve_tools surfaces an integration for the source, activate_integration it "
        "and use its tools: that beats scraping the same data off the public web, which is "
        "the mistake this rule exists to stop. Do NOT curl an API or scrape a site in bash "
        "when an integration or tool covers it.",
    ),
    (
        'The mistake is querying "fetch webpage content" for a Hacker News request and '
        "missing subagent:hackernews.",
        'The mistake is querying "fetch webpage content" for a Hacker News request and '
        "missing the hackernews integration.",
    ),
    (
        "NEVER route a reminder\n     to subagent:todos.",
        'NEVER route a reminder\n     to the "todos" integration.',
    ),
    (
        "never name a provider in a task you send to subagent:todos.",
        'never name a provider in work you do with the "todos" integration.',
    ),
    (
        "subagent:todos is GAIA's list and nothing else.",
        'The "todos" integration is GAIA\'s list and nothing else.',
    ),
    (
        "each provider subagent reloads its whole toolset (~20s of pure overhead) and usually repeats the same outcome",
        "each spawn repeats the same setup cost and usually repeats the same outcome",
    ),
    (
        "Spawning the same provider subagent more than once for a single request is almost always a mistake",
        "Spawning the same worker more than once for a single request is almost always a mistake",
    ),
    (
        "hand off to THAT provider's subagent instead, and",
        "activate THAT provider's integration instead, and",
    ),
    (
        "Emails ALWAYS go through the draft flow (the gmail subagent drafts → user confirms → then send), never compose-and-send in one shot.",
        "Emails ALWAYS go through the draft flow (draft with the gmail integration's tools → user confirms → then send), never compose-and-send in one shot.",
    ),
)


def build_activation_executor_prompt() -> str:
    """EXECUTOR_AGENT_PROMPT rewritten to teach activation instead of handoff.

    Stale anchors degrade with a warning, never raise: this runs at import.
    """
    prompt = EXECUTOR_AGENT_PROMPT
    for anchor, replacement in _PHRASE_REWRITES:
        if anchor not in prompt:
            log.warning("activation_prompt.stale_phrase_anchor_skipped", anchor=anchor[:80])
            continue
        prompt = prompt.replace(anchor, replacement)
    return prompt
