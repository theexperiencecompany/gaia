const SLACK_BOT_SCOPES = [
  "chat:write",
  "commands",
  "im:history",
  "im:read",
  "im:write",
].join(",");

/** Read a bot's OAuth client id, failing the request rather than sending people to an install screen with no app. */
function requireClientId(name: string, value: string | undefined): string {
  if (!value)
    throw new Error(
      `${name} is unset, so the bot install link cannot be built`,
    );
  return value;
}

/** Discord's OAuth screen that adds the GAIA bot to a server. */
export function discordInstallUrl(): string {
  const url = new URL("https://discord.com/oauth2/authorize");
  url.searchParams.set(
    "client_id",
    requireClientId(
      "NEXT_PUBLIC_DISCORD_CLIENT_ID",
      process.env.NEXT_PUBLIC_DISCORD_CLIENT_ID,
    ),
  );
  url.searchParams.set("scope", "bot applications.commands");
  url.searchParams.set("permissions", "2048");
  return url.toString();
}

/** Slack's OAuth screen that installs the GAIA app in a workspace. */
export function slackInstallUrl(): string {
  const url = new URL("https://slack.com/oauth/v2/authorize");
  url.searchParams.set(
    "client_id",
    requireClientId(
      "NEXT_PUBLIC_SLACK_CLIENT_ID",
      process.env.NEXT_PUBLIC_SLACK_CLIENT_ID,
    ),
  );
  url.searchParams.set("scope", SLACK_BOT_SCOPES);
  return url.toString();
}
