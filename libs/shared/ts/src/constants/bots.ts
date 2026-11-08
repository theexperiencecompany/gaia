/**
 * The handles GAIA's hosted bots answer on. A self-hosted instance reaches its
 * own bots through /setup/status instead, so these are the hosted defaults.
 */
import { telegramBotUrl } from "../utils/botLinks";

/** E.164 without the plus, the form wa.me links take. */
export const WHATSAPP_BOT_NUMBER = "12038429512";

/** Telegram's handle for the GAIA bot, without the @. */
export const TELEGRAM_BOT_USERNAME = "heygaia_bot";

/** Invite code for the GAIA community server; discord.heygaia.io redirects here. */
export const DISCORD_INVITE_CODE = "puRWnQ7hV5";

/** The link every surface shows; the redirect, not the code, is what ships. */
export const DISCORD_COMMUNITY_URL = "https://discord.heygaia.io";

/** Ready-to-open links, so no caller spells a handle into a URL. */
export const BOT_URLS = {
  whatsapp: `https://wa.me/${WHATSAPP_BOT_NUMBER}`,
  telegram: telegramBotUrl(TELEGRAM_BOT_USERNAME),
  discord: DISCORD_COMMUNITY_URL,
} as const;
