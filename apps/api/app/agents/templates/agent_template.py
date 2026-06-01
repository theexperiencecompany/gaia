"""Static agent prompt templates, per-channel.

These strings are passed verbatim to LangChain as the system prompt. They are
free of user-specific interpolation so they are byte-identical across every
user on a given channel. That lets the LLM provider's implicit prompt cache
match across users — the first request of the day on web warms the cache and
every subsequent web user hits it on turn 1.

Each channel's static prompt is the base comms prompt plus the output-format
block that applies to that channel (OpenUI component library on renderable
channels; text-only restrictions everywhere else). Dynamic per-user/per-turn
context (user name, timezone, preferences, memories, current time) is carried
in a separate dynamic-context system message placed AFTER this one.
"""

from typing import Final

from app.agents.prompts.comms_prompts import (
    COMMS_AGENT_PROMPT,
    EXECUTOR_AGENT_PROMPT,
    _strip_openui_section,
)
from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS
from app.agents.workspace.operational_docs import GAIA_CORE

# Base comms prompt with the embedded OpenUI component-instructions section
# stripped out, so the per-channel addendum below is the single source of
# truth for output format. Pre-computed once at import so the bytes stay
# stable per channel (cache-friendly).
_COMMS_AGENT_PROMPT_BASE: Final[str] = _strip_openui_section(COMMS_AGENT_PROMPT)


# Output-format addendum for renderable channels (web, mobile, desktop).
_OPENUI_ADDENDUM: Final[str] = "\n\n" + OPENUI_INSTRUCTIONS


# Output-format addendum for each text-only channel. These strings are the
# platform-specific formatting rules the LLM must stick to. We inline them
# here so the addendum is byte-identical across every WhatsApp user, etc.
def _text_only_addendum(platform_name: str, formatting: str) -> str:
    return f"""

—Platform Context (IMPORTANT)—
The user is messaging from **{platform_name}**. This is a text-based messaging platform.

OUTPUT RESTRICTIONS for this platform:
- NO HTML, interactive UI components, artifacts, or rich cards — the user cannot see them
- NO markdown links [text](url) — just paste URLs directly
- NO tables — use simple lists instead
- NO images or embedded media in your response
- Keep formatting simple and compatible: {formatting}
- The user CANNOT see tool_data UI, MCP apps, or any frontend components
- When showing structured data (search results, calendar events, emails, etc.), format as clean text lists
- Artifacts and HTML content blocks are invisible to the user — describe results in plain text instead

WHAT TO DO INSTEAD:
- Present all information as formatted text using the platform's native formatting
- For data that would normally show as a card/component, write it out as a clear text summary
- For content that would be an artifact, include it directly in your message as text
- Keep messages concise — messaging platforms work best with shorter, focused messages"""


_WHATSAPP_ADDENDUM: Final[str] = _text_only_addendum(
    "WhatsApp",
    "WhatsApp formatting: *bold*, _italic_, ~strikethrough~, ```code```",
)
_TELEGRAM_ADDENDUM: Final[str] = _text_only_addendum(
    "Telegram",
    "Telegram formatting: **bold**, _italic_, `code`, ```code blocks```",
)
_DISCORD_ADDENDUM: Final[str] = _text_only_addendum(
    "Discord",
    "Discord formatting: **bold**, *italic*, ~~strikethrough~~, `code`, ```code blocks```, > quotes",
)
_SLACK_ADDENDUM: Final[str] = _text_only_addendum(
    "Slack",
    "Slack formatting: *bold*, _italic_, ~strikethrough~, `code`, ```code blocks```, > quotes",
)


# Pre-assembled static comms prompts per channel. Each is a single Python
# string literal that lives for the process lifetime, so the bytes sent to
# the LLM are identical for every user on that channel.
COMMS_PROMPT_BY_SOURCE: Final[dict[str, str]] = {
    "web": _COMMS_AGENT_PROMPT_BASE + _OPENUI_ADDENDUM,
    "mobile": _COMMS_AGENT_PROMPT_BASE + _OPENUI_ADDENDUM,
    "desktop": _COMMS_AGENT_PROMPT_BASE + _OPENUI_ADDENDUM,
    "whatsapp": _COMMS_AGENT_PROMPT_BASE + _WHATSAPP_ADDENDUM,
    "telegram": _COMMS_AGENT_PROMPT_BASE + _TELEGRAM_ADDENDUM,
    "discord": _COMMS_AGENT_PROMPT_BASE + _DISCORD_ADDENDUM,
    "slack": _COMMS_AGENT_PROMPT_BASE + _SLACK_ADDENDUM,
}

# Default (web-style) static prompt used when ``source`` is unknown/None.
COMMS_PROMPT_DEFAULT: Final[str] = COMMS_PROMPT_BY_SOURCE["web"]


def get_comms_static_prompt(source: str | None) -> str:
    """Return the per-channel static comms prompt.

    The choice of channel-specific static prompt means the provider's
    implicit prompt cache can match byte-for-byte across all users on the
    same channel. Unknown sources fall back to the web variant.
    """
    if not source:
        return COMMS_PROMPT_DEFAULT
    return COMMS_PROMPT_BY_SOURCE.get(source.strip().lower(), COMMS_PROMPT_DEFAULT)


# Legacy name still imported by a few call sites. Kept as an alias for the
# default web-style prompt; all per-channel users should go through
# ``get_comms_static_prompt``.
COMMS_PROMPT_TEMPLATE: Final[str] = COMMS_PROMPT_DEFAULT

# The executor's static prefix carries the always-on operating core (GAIA_CORE):
# user-independent self-knowledge + the self-management capability menu + the
# read_manual topic routing. It is appended here (not interpolated per user) so
# the whole executor prompt stays byte-identical across users and rides the
# provider's prompt cache.
EXECUTOR_PROMPT_TEMPLATE: Final[str] = EXECUTOR_AGENT_PROMPT + "\n\n" + GAIA_CORE
