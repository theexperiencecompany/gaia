/**
 * Short heygaia.io paths that only forward somewhere else (a community, a
 * status page). They are edge redirects in next.config, never pages: a page
 * that calls redirect() is prerendered as a 200 with a meta refresh, which
 * search engines index as a thin page of its own. The bot install links carry
 * an OAuth client id in their query, so they are route handlers instead
 * (/discord-bot, /slack-bot).
 */

export const VANITY_REDIRECT_PAIRS = [
  ["/discord", "https://discord.heygaia.io"],
  ["/whatsapp", "https://whatsapp.heygaia.io"],
  ["/docs", "https://docs.heygaia.io"],
  ["/status", "https://status.heygaia.io"],
  ["/roadmap", "https://gaia.featurebase.app/roadmap"],
  ["/request-feature", "https://gaia.featurebase.app"],
  ["/desktop", "/download"],
  ["/support", "/contact"],
  ["/self-host", "/cli"],
];

const TARGET_BY_PATH = new Map(VANITY_REDIRECT_PAIRS);

/** Where a vanity path forwards, so a link goes straight there instead of through the redirect. */
export function vanityTarget(path) {
  const target = TARGET_BY_PATH.get(path);
  if (target === undefined) throw new Error(`${path} is not a vanity path`);
  return target;
}

/** Every vanity redirect as Next redirects() entries. */
export function vanityRedirects() {
  return VANITY_REDIRECT_PAIRS.map(([source, destination]) => ({
    source,
    destination,
    permanent: true,
  }));
}
