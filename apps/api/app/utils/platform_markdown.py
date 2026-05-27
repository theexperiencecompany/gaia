"""Convert CommonMark-style Markdown output from the agent to the native
formatting each messaging platform expects.

The agent produces standard Markdown (`**bold**`, `### heading`, `[label](url)`
etc). Sending that raw to WhatsApp or Slack renders the asterisks literally
because their formatting syntax is different. Use these helpers at the
platform adapter boundary so users see proper bold/italic instead of
`**raw markdown**`.

Kept in sync with ``libs/shared/ts/src/bots/utils/formatters.ts`` — any
change to the bot converters should be mirrored here and vice versa.
"""

from __future__ import annotations

from collections.abc import Callable
import re

_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")


def _apply_outside_code_blocks(text: str, transform: Callable[[str], str]) -> str:
    """Apply ``transform`` to every segment of ``text`` that is NOT inside a
    fenced code block, leaving ``` ... ``` blocks unchanged."""
    parts: list[str] = []
    last_index = 0
    for match in _FENCED_CODE_RE.finditer(text):
        parts.append(transform(text[last_index : match.start()]))
        parts.append(match.group(0))
        last_index = match.end()
    parts.append(transform(text[last_index:]))
    return "".join(parts)


def _convert_to_whatsapp(segment: str) -> str:
    segment = re.sub(r"\*\*\*([^*]+)\*\*\*", r"*\1*", segment)
    segment = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", segment)
    segment = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", segment)
    segment = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", segment, flags=re.MULTILINE)
    segment = re.sub(r"^>\s*", "", segment, flags=re.MULTILINE)
    segment = re.sub(r"^[-_]{3,}$", "", segment, flags=re.MULTILINE)
    return segment


def _convert_to_slack(segment: str) -> str:
    segment = re.sub(r"\*\*\*(.+?)\*\*\*", r"*\1*", segment)
    segment = re.sub(r"\*\*(.+?)\*\*", r"*\1*", segment)
    segment = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", segment)
    segment = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", segment, flags=re.MULTILINE)
    segment = re.sub(r"^>\s*", "", segment, flags=re.MULTILINE)
    segment = re.sub(r"^[-_]{3,}$", "", segment, flags=re.MULTILINE)
    return segment


def convert_to_whatsapp_markdown(text: str) -> str:
    """Convert CommonMark Markdown to WhatsApp's formatting rules.

    WhatsApp supports ``*bold*`` (single asterisk), ``_italic_``,
    ``~strikethrough~``, and ``` `code` ```. It has no native headings or
    link syntax. ``[label](url)`` is rendered as ``label (url)``.
    """
    if not text:
        return text
    return _apply_outside_code_blocks(text, _convert_to_whatsapp)


def convert_to_slack_mrkdwn(text: str) -> str:
    """Convert CommonMark Markdown to Slack's mrkdwn."""
    if not text:
        return text
    return _apply_outside_code_blocks(text, _convert_to_slack)
