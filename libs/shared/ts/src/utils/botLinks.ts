/**
 * Links to a chat bot from its public handle, shared by the CLI (`gaia bots add`)
 * and the web Bots page so both point at the same place.
 * @module utils/botLinks
 */

/** Send Messages: the one permission a Discord bot's invite link asks for. */
const DISCORD_INVITE_PERMISSIONS = "2048";

/** The link that adds a Discord bot to a server, with its slash commands. */
export function discordInviteUrl(applicationId: string): string {
  const url = new URL("https://discord.com/oauth2/authorize");
  url.searchParams.set("client_id", applicationId);
  url.searchParams.set("scope", "bot applications.commands");
  url.searchParams.set("permissions", DISCORD_INVITE_PERMISSIONS);
  return url.toString();
}

/** The chat with a Telegram bot. */
export function telegramBotUrl(username: string): string {
  return `https://t.me/${username}`;
}
