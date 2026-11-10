"""GAIA's hosted bot identity, read from the file the web bundle imports.

libs/shared/bot-identity.json is the single copy of the handles; this module is
its Python face, so the hosted defaults the API serves cannot drift from the
ones the website links to. Self-hosted instances still override with env.
"""

from importlib.resources import files
import json

_IDENTITY = json.loads((files("shared") / "bot-identity.json").read_text(encoding="utf-8"))

WHATSAPP_NUMBER: str = _IDENTITY["whatsappNumber"]
TELEGRAM_USERNAME: str = _IDENTITY["telegramUsername"]
DISCORD_INVITE_CODE: str = _IDENTITY["discordInviteCode"]
DISCORD_COMMUNITY_URL: str = _IDENTITY["discordCommunityUrl"]
DISCORD_CLIENT_ID: str = _IDENTITY["discordClientId"]
SLACK_CLIENT_ID: str = _IDENTITY["slackClientId"]
