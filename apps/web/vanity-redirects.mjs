/**
 * Short heygaia.io paths that only forward somewhere else (a community, a
 * status page), and retired pages pointing at their replacement. They are edge
 * redirects in next.config, never pages: a page that calls redirect() is
 * prerendered as a 200 with a meta refresh, which search engines index as a
 * thin page of its own. The bot install links carry an OAuth client id in
 * their query, so they are route handlers instead (/discord-bot, /slack-bot).
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
  // GAIA has no mobile app; on a phone it is used through chat apps.
  ["/features/mobile", "/ai-assistant-whatsapp-telegram-imessage"],
];

/** Every vanity redirect as Next redirects() entries. */
export function vanityRedirects() {
  return PERMANENT.map(([source, destination]) => ({
    source,
    destination,
    permanent: true,
  }));
}
