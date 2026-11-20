/**
 * /settings has no page of its own: it forwards to a section. These are edge
 * redirects in next.config, never a page that calls redirect(): under the
 * (main) loading boundary such a page streams a 200 whose meta refresh reloads
 * the whole document a second later. Plain-js because next.config.mjs (Node)
 * imports it and cannot load TS.
 */

export const DEFAULT_SETTINGS_SECTION = "account";

/** /settings, and the legacy /settings?section=X links bots still send, as Next redirects() entries. */
export function settingsRedirects() {
  return [
    {
      source: "/settings",
      has: [{ type: "query", key: "section", value: "(?<section>[a-z-]+)" }],
      destination: "/settings/:section",
      permanent: false,
    },
    {
      source: "/settings",
      destination: `/settings/${DEFAULT_SETTINGS_SECTION}`,
      permanent: false,
    },
  ];
}
