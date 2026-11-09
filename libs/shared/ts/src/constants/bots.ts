/**
 * GAIA's hosted bot identity. The values live in libs/shared/bot-identity.json
 * so the web, the API and the upstream check read one file; this module is the
 * typed face of it and the only place URLs are assembled from the handles.
 */
import identity from "../../../bot-identity.json";
import { telegramBotUrl } from "../utils/botLinks";

/** E.164 without the plus, the form wa.me links take. */
export const WHATSAPP_BOT_NUMBER = identity.whatsappNumber;

/** Telegram's handle for the GAIA bot, without the @. */
export const TELEGRAM_BOT_USERNAME = identity.telegramUsername;

/** Invite code for the GAIA community server; discord.heygaia.io redirects here. */
export const DISCORD_INVITE_CODE = identity.discordInviteCode;

/** The link every surface shows; the redirect, not the code, is what ships. */
export const DISCORD_COMMUNITY_URL = identity.discordCommunityUrl;

/** Public application ids, the half of OAuth that may live in the repo. */
export const DISCORD_CLIENT_ID = identity.discordClientId;
export const SLACK_CLIENT_ID = identity.slackClientId;

/** Ready-to-open links, so no caller spells a handle into a URL. */
export const BOT_URLS = {
  whatsapp: `https://wa.me/${WHATSAPP_BOT_NUMBER}`,
  telegram: telegramBotUrl(TELEGRAM_BOT_USERNAME),
  discord: DISCORD_COMMUNITY_URL,
} as const;
