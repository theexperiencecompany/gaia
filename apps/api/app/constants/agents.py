"""Internal agent-to-agent channel tags.

The tiers hand work to each other asynchronously — executor results reach comms,
subagent results reach the executor — and the handoff is plain text landing in
the next tier's context. These XML-style tags frame that text: they say where an
internal payload starts, where it ends, and that it is addressed to the agent and
never to the user.

XML tags rather than the bare ``[MARKER]`` prefixes they replace, for two
reasons. A prefix only marks a start, so the model has to infer where the
internal payload stops and its own reply begins; an open/close pair states it.
And models are trained on tagged context blocks, so a tag reads as machine
framing while a bracketed word reads as text worth copying — which is exactly how
``[EXECUTOR_RESULT]`` kept surfacing at the top of user-facing replies.

This module owns the vocabulary AND the framing, so the site that writes a tag
and the site that strips one (``strip_internal_agent_tags``) can never disagree
about the syntax.
"""

from enum import StrEnum
import re


class AgentTag(StrEnum):
    """Tag names framing an internal payload passed between agent tiers."""

    EXECUTOR_RESULT = "executor_result"
    EXECUTOR_ERROR = "executor_error"
    EXECUTOR_CANCELLED = "executor_cancelled"
    RETURNED_TO_FRONTEND = "returned_to_frontend"
    PLATFORM_DELIVERY = "platform_delivery"
    DELIVERY_INSTRUCTIONS = "delivery_instructions"
    SUBAGENT_RESULT = "subagent_result"
    STYLE_CORRECTION = "style_correction"


def wrap_agent_payload(tag: AgentTag, body: str, agent: str | None = None) -> str:
    """Frame an internal payload in its channel tag.

    ``agent`` names the tier that produced the payload, which only a
    ``<subagent_result>`` carries — several land in one collection and the
    executor has to tell whose report is whose.

    Trailing newline included so consecutive blocks concatenate into one
    readable document without the caller managing separators.
    """
    attribution = f' agent="{agent}"' if agent else ""
    return f"<{tag}{attribution}>\n{body.strip()}\n</{tag}>\n"


# Every internal tag, open or close, with or without attributes. Stripped
# deterministically before delivery (see ``strip_internal_agent_tags``) as the
# hard backstop for a weak model echoing its context into the reply.
INTERNAL_AGENT_TAG_PATTERN = re.compile(
    rf"</?(?:{'|'.join(tag.value for tag in AgentTag)})(?:\s[^>]*)?>",
    flags=re.IGNORECASE,
)
