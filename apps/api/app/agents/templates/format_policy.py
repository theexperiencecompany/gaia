"""How a reply is formatted for the surface it is read on: the prompt block that asks for it, and the check on what came back.

One FormatPolicy per surface. The app surfaces render :::openui components; a call and the
chat apps cannot, so a block the model wrote anyway is dropped (loudly) before the text is sent.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.constants.reactions import TELEGRAM_REACTION_PALETTE
from app.utils.message_breaks import openui_ranges
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER
from shared.py.wide_events import log

# Approvals inside the app (web, mobile, desktop and a voice call) are decided on a card.
_APP_APPROVALS: Final[str] = (
    "\n## Approvals in the app\n"
    "An action that needs the user's go-ahead renders as an approval card they can "
    "approve or decline on screen. While one is pending, tell them an approval needs "
    "their decision and point them at the card; they decide from the card, so do not "
    "ask them to type a reply in chat.\n"
)

# Output-format addendum for renderable channels (web, mobile, desktop).
_OPENUI_ADDENDUM: Final[str] = "\n" + OPENUI_INSTRUCTIONS + _APP_APPROVALS

# A voice reply is spoken by text-to-speech, so it carries no markup or components.
_VOICE_ADDENDUM: Final[str] = """

## Platform Context (IMPORTANT)
The user is talking to you on a voice call, and your reply is read aloud to them. Write only what a person would say out loud.

OUTPUT RESTRICTIONS for a call:
- NO markdown of any kind: no headings, bold, italics, tables, lists, code blocks or links. The speech engine reads symbols literally or drops them.
- NO components, cards or rich UI in your reply. Describe a result in a sentence or two instead.
- NO URLs read out. Say where they can find it in the app instead.
- Keep it short and conversational, a few spoken sentences. Give the key fact first; offer more if they want it.
"""

# Text-only channels have no approval card, so an action awaiting go-ahead must
# invite a chat reply. Approval is permission, not execution: the action stays unrun
# until the user decides, and the HIL resolver commits their yes/no reply.
_MESSAGING_APPROVAL: Final[str] = (
    "APPROVALS ON THIS PLATFORM:\n"
    "- When an action needs the user's approval, it does not run until they decide. "
    "There is no approval card or button here for them to see or click. Tell them "
    "plainly to reply YES to approve or NO to decline; their Yes or No (or "
    '"go ahead" / "no, don\'t") reply in the chat is what decides it, and GAIA then '
    "carries the action out or leaves it undone.\n\n"
)


# Desktop-app capability addendum. The comms agent has no desktop tools
# itself — it delegates to the executor, which discovers them via retrieval.
_DESKTOP_ADDENDUM: Final[str] = """

## Desktop Context
The user is chatting from the GAIA desktop app on their computer. Through the
executor, GAIA can act on that computer: look at the screen (take_screenshot),
read or write the clipboard, open applications, open URLs in the browser, and
list open windows. When the user references "this", "my screen", or something
they are currently looking at, delegate to the executor and have it take a
screenshot for visual context."""


# Output-format addendum per text-only channel, inlined for byte-identical
# output. LAST thing the model reads, far after Bubbles, so the bubble rule
# is restated here as a backstop to the bot layer's own split.
def _text_only_addendum(platform_name: str, formatting: str, reactions: str = "") -> str:
    return f"""

## Platform Context (IMPORTANT)
The user is messaging from **{platform_name}**. This is a text-based messaging platform, so your reply arrives as one or more real chat messages and nothing else.

{_MESSAGING_APPROVAL}BUBBLES ON THIS PLATFORM (restated here because it matters most here):
- Every conversational beat is its own bubble, separated by {NEW_MESSAGE_BREAKER}. So is every paragraph of prose: on a messaging app a three-paragraph block is three messages, the way a person actually texts.
- Structured content stays WHOLE in one bubble: a list, a set of bullets, a table written out as a list, a code block, a set of numbered steps. Splitting one of those breaks it into fragments that no longer read as one thing.
- Aim for about 600 characters per bubble. When a bubble runs long, SPLIT IT, and never solve it by cutting content: the data goes out in full across more bubbles.
- So a three-paragraph answer leaves you as: first paragraph, {NEW_MESSAGE_BREAKER}, second paragraph, {NEW_MESSAGE_BREAKER}, third paragraph. Sending a multi-paragraph answer as one message is the single most common way this goes wrong. The token is the only splitter: emit none and the whole reply ships as one message, no matter how many blank lines it has. At most 4 bubbles per reply.

OUTPUT RESTRICTIONS for this platform:
- NO HTML, interactive UI components, artifacts, or rich cards, since the user cannot see them
- NO markdown links [text](url). Paste the bare URL on its own line and let the platform link it. This overrides the clickable-markdown rule in Delivering Results, which applies only to the app.
- NO tables. Write the same rows as a flat list.
- NO nested lists. One level of bullets only; a sub-point becomes its own line or its own bubble.
- NO bold and NO italics, at all, in a chat reply. Not for a key number, not for a heading, not to make a point land. Emphasis here is word choice and rhythm; bolded fragments scattered through a chat message are a formatting tic that reads as generated text. The only formatting syntax you may use here is for code: {formatting}
- NO images or embedded media in your response
- The user CANNOT see tool_data UI, MCP apps, or any frontend components
- When showing structured data (search results, calendar events, emails, etc.), format as clean text lists
- Artifacts and HTML content blocks are invisible to the user, so describe results in plain text instead
- When an integration needs to be connected: paste the connect URL directly in your reply. There is no connect button on this platform, so the URL is the only way for the user to connect

WHAT TO DO INSTEAD:
- Present all information as plain text lines and, where there are genuinely separate items, one flat level of bullets
- For data that would normally show as a card/component, write it out as a clear text summary
- For content that would be an artifact, include it directly in your message as text
- Concise here means cutting filler, never cutting data a result carried. Trim your own wrapper words, then split what is left across bubbles. Delivering the data they asked for still outranks brevity.{reactions}"""


# Telegram's reaction API takes only a fixed emoji set, listed from the palette the react tool checks.
_TELEGRAM_REACTIONS: Final[str] = (
    "\n\nREACTIONS ON TELEGRAM: a reaction attaches to their message only with one of "
    f"{' '.join(TELEGRAM_REACTION_PALETTE)}. Pick from these; any other emoji is refused."
)


_WHATSAPP_ADDENDUM: Final[str] = _text_only_addendum(
    "WhatsApp",
    "WhatsApp code formatting: ```code```",
)
_TELEGRAM_ADDENDUM: Final[str] = _text_only_addendum(
    "Telegram",
    "Telegram code formatting: `code`, ```code blocks```",
    _TELEGRAM_REACTIONS,
)
_DISCORD_ADDENDUM: Final[str] = _text_only_addendum(
    "Discord",
    "Discord code formatting: `code`, ```code blocks```, > quotes",
)
_IMESSAGE_ADDENDUM: Final[str] = _text_only_addendum(
    "iMessage",
    "iMessage shows no markup at all; a fenced ```code block``` is kept verbatim",
)
_SLACK_ADDENDUM: Final[str] = _text_only_addendum(
    "Slack",
    "Slack code formatting: `code`, ```code blocks```, > quotes",
)


@dataclass(frozen=True, slots=True)
class FormatPolicy:
    """The output-format block a surface's prompt ends with, and whether the surface renders :::openui."""

    addendum: str
    renders_openui: bool

    def sanitize(self, text: str, surface: ConversationSource) -> str:
        """Return text as this surface can show it: an :::openui block is dropped where nothing renders it."""
        if self.renders_openui:
            return text
        blocks = openui_ranges(text)
        if not blocks:
            return text
        log.warning(
            f"{LogTag.AGENT} OpenUI written for a surface that cannot render it; dropped",
            surface=surface.value,
            blocks=len(blocks),
        )
        kept, cursor = [], 0
        for start, end in blocks:
            kept.append(text[cursor:start])
            cursor = end
        kept.append(text[cursor:])
        return "".join(kept).strip()


_APP = FormatPolicy(_OPENUI_ADDENDUM, renders_openui=True)

# A background or workflow reply kept in the app is read there, so it takes the app's policy.
FORMAT_POLICY_BY_SOURCE: Final[Mapping[ConversationSource, FormatPolicy]] = MappingProxyType(
    {
        ConversationSource.WEB: _APP,
        ConversationSource.MOBILE: _APP,
        ConversationSource.DESKTOP: FormatPolicy(
            _OPENUI_ADDENDUM + _DESKTOP_ADDENDUM, renders_openui=True
        ),
        ConversationSource.WORKFLOW_SYSTEM: _APP,
        ConversationSource.BACKGROUND: _APP,
        ConversationSource.VOICE: FormatPolicy(
            _APP_APPROVALS + _VOICE_ADDENDUM, renders_openui=False
        ),
        ConversationSource.WHATSAPP: FormatPolicy(_WHATSAPP_ADDENDUM, renders_openui=False),
        ConversationSource.TELEGRAM: FormatPolicy(_TELEGRAM_ADDENDUM, renders_openui=False),
        ConversationSource.DISCORD: FormatPolicy(_DISCORD_ADDENDUM, renders_openui=False),
        ConversationSource.SLACK: FormatPolicy(_SLACK_ADDENDUM, renders_openui=False),
        ConversationSource.IMESSAGE: FormatPolicy(_IMESSAGE_ADDENDUM, renders_openui=False),
    }
)
