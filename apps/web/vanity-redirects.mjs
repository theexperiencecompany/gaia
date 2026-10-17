/**
 * Short heygaia.io paths that only forward somewhere else (a community, a
 * status page, a bot install). They are edge redirects in next.config, never
 * pages: a page that calls redirect() is prerendered as a 200 with a meta
 * refresh, which search engines index as a thin page of its own.
 */

const PERMANENT = [
  ["/discord", "https://discord.heygaia.io"],
  ["/whatsapp", "https://whatsapp.heygaia.io"],
  ["/docs", "https://docs.heygaia.io"],
  ["/status", "https://status.heygaia.io"],
  ["/roadmap", "https://gaia.featurebase.app/roadmap"],
  ["/request-feature", "https://gaia.featurebase.app"],
  ["/desktop", "/download"],
  ["/support", "/contact"],
];

const SLACK_BOT_SCOPES = [
  "chat:write",
  "commands",
  "im:history",
  "im:read",
  "im:write",
].join(",");

/**
 * Bot install links carry the OAuth client id, so they are temporary: the id is
 * configuration, not an address. Only the prod deploy build sets the ids; the
 * post-deploy SEO audit asserts both links redirect on the live site.
 */
function botInstallRedirects(env) {
  const installs = [
    [
      "/discord-bot",
      env.NEXT_PUBLIC_DISCORD_CLIENT_ID,
      (id) =>
        `https://discord.com/oauth2/authorize?client_id=${id}&scope=${encodeURIComponent("bot applications.commands")}&permissions=2048`,
    ],
    [
      "/slack-bot",
      env.NEXT_PUBLIC_SLACK_CLIENT_ID,
      (id) =>
        `https://slack.com/oauth/v2/authorize?client_id=${id}&scope=${encodeURIComponent(SLACK_BOT_SCOPES)}`,
    ],
  ];
  return installs.flatMap(([source, clientId, url]) => {
    if (clientId) return [{ source, destination: url(clientId), permanent: false }];
    console.warn(`vanity-redirects: ${source} skipped, its OAuth client id is unset in this build`);
    return [];
  });
}

/** Every vanity redirect as Next redirects() entries. */
export function vanityRedirects(env = process.env) {
  return [
    ...PERMANENT.map(([source, destination]) => ({
      source,
      destination,
      permanent: true,
    })),
    ...botInstallRedirects(env),
  ];
}
