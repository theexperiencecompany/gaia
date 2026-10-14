/**
 * Checks a chat bot's credentials against its platform before they are saved,
 * so a typo fails here with the platform's reason instead of as a bot
 * container that restarts forever.
 * @module lib/bot-tokens
 */

const REQUEST_TIMEOUT_MS = 10_000;

/** Discord application flags: the Message Content intent, full or limited. */
const DISCORD_MESSAGE_CONTENT_FLAGS = (1 << 18) | (1 << 19);

/** Send Messages: the one permission the bot's invite link asks for. */
const DISCORD_INVITE_PERMISSIONS = "2048";

async function fetchJson<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return (await response.json()) as T;
}

interface TelegramGetMe {
  ok: boolean;
  description?: string;
  result?: { username: string };
}

/** The bot's @username; Telegram's `getMe` doubles as the token check. */
export async function verifyTelegramToken(token: string): Promise<string> {
  const body = await fetchJson<TelegramGetMe>(
    `https://api.telegram.org/bot${token}/getMe`,
    { method: "GET" },
  );
  if (!body.ok || !body.result) {
    throw new Error(
      `Telegram rejected the bot token: ${body.description ?? "unknown error"}. Copy it again from @BotFather.`,
    );
  }
  return body.result.username;
}

interface DiscordApplication {
  id?: string;
  flags?: number;
  message?: string;
}

/** The application id (DISCORD_CLIENT_ID) the token belongs to. */
export async function verifyDiscordToken(token: string): Promise<string> {
  const body = await fetchJson<DiscordApplication>(
    "https://discord.com/api/v10/applications/@me",
    { method: "GET", headers: { Authorization: `Bot ${token}` } },
  );
  if (!body.id) {
    throw new Error(
      `Discord rejected the bot token: ${body.message ?? "unknown error"}. Reset and copy it from the Developer Portal's Bot page.`,
    );
  }
  if (((body.flags ?? 0) & DISCORD_MESSAGE_CONTENT_FLAGS) === 0) {
    throw new Error(
      "Turn on Message Content Intent in the Discord Developer Portal (Bot page, Privileged Gateway Intents), then rerun this command.",
    );
  }
  return body.id;
}

/** The link that adds the bot to a server, with slash commands. */
export function discordInviteUrl(applicationId: string): string {
  const url = new URL("https://discord.com/oauth2/authorize");
  url.searchParams.set("client_id", applicationId);
  url.searchParams.set("scope", "bot applications.commands");
  url.searchParams.set("permissions", DISCORD_INVITE_PERMISSIONS);
  return url.toString();
}

interface SlackResponse {
  ok: boolean;
  error?: string;
  team?: string;
}

async function callSlack(
  method: string,
  token: string,
): Promise<SlackResponse> {
  return await fetchJson<SlackResponse>(`https://slack.com/api/${method}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

/**
 * The workspace the bot token is installed in. The app token is checked by
 * opening (and never using) a Socket Mode URL, which also proves Socket Mode is on.
 */
export async function verifySlackTokens(
  botToken: string,
  appToken: string,
): Promise<string> {
  const auth = await callSlack("auth.test", botToken);
  if (!auth.ok || !auth.team) {
    throw new Error(
      `Slack rejected the bot token (xoxb-): ${auth.error ?? "unknown error"}.`,
    );
  }
  const socket = await callSlack("apps.connections.open", appToken);
  if (!socket.ok) {
    throw new Error(
      `Slack rejected the app token (xapp-): ${socket.error ?? "unknown error"}. Enable Socket Mode and create an app-level token with connections:write.`,
    );
  }
  return auth.team;
}
