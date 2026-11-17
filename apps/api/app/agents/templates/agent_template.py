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

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT, EXECUTOR_AGENT_PROMPT
from app.agents.prompts.todo_prompts import TODO_SYSTEM_PROMPT
from app.agents.prompts.user_instructions_prompts import INSTRUCTION_PRECEDENCE_RULES
from app.agents.templates.format_policy import FORMAT_POLICY_BY_SOURCE
from app.agents.workspace.operational_docs import GAIA_CORE
from app.constants.chat import ConversationSource

# One byte-identical prompt per surface, so the provider cache matches across users.
COMMS_PROMPT_BY_SOURCE: Final[Mapping[ConversationSource, str]] = MappingProxyType(
    {
        source: COMMS_AGENT_PROMPT + policy.addendum
        for source, policy in FORMAT_POLICY_BY_SOURCE.items()
    }
)


def get_comms_static_prompt(source: ConversationSource) -> str:
    """Return the static comms prompt of the surface the reply is read on.

    Every surface has one, so a value outside the enum raises KeyError rather than reading as web.
    """
    return COMMS_PROMPT_BY_SOURCE[source]


def get_executor_prompt() -> str:
    """Return the static executor prompt; GAIA_CORE is appended, not interpolated, for a stable provider cache."""
    return (
        f"{EXECUTOR_AGENT_PROMPT}\n\n{INSTRUCTION_PRECEDENCE_RULES}\n\n"
        f"{GAIA_CORE}\n\n{TODO_SYSTEM_PROMPT}"
    )


EXECUTOR_PROMPT_TEMPLATE: Final[str] = get_executor_prompt()
