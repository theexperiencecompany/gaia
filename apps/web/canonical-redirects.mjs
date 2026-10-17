/**
 * Canonical URL consolidation redirects — the routing half of the
 * `canonicalSlug`/`canonicalPath` markers in the per-slug JSON files under
 * `public/data` (e.g. `public/data/combos/{victim}.json`).
 *
 * Each pair below is one marked loser page: the destination is the
 * higher-impression canonical (GSC audit, 2026-07-19 → 2026-10-17). The JSON
 * markers are the source of truth — public/data JSONs say "this page defers
 * to X"; this table says the same thing to the router. A vitest
 * (`src/__tests__/canonical-redirects.test.ts`) derives the expected pairs
 * back from the JSON data and fails if the two drift apart.
 *
 * Plain-js on purpose: `next.config.mjs` (Node) and the vitest suite both
 * import this — TS modules can't be loaded by next.config.
 *
 * Locale prefixes mirror `src/i18n/config.ts` (the en default has none).
 */

const CANONICAL_REDIRECT_PAIRS = [
  // /automate reverse-order combos
  ["/automate/teams-slack", "/automate/slack-teams"],
  ["/automate/trello-notion", "/automate/notion-trello"],
  // /compare vs /alternative-to same-tool pairs
  ["/alternative-to/superhuman", "/compare/superhuman"],
  ["/compare/limitless-ai", "/alternative-to/limitless-ai"],
  ["/compare/sunsama", "/alternative-to/sunsama"],
  ["/alternative-to/shortwave", "/compare/shortwave"],
  // /learn glossary wiring (canonicalSlug existed in data, unwired until now)
  ["/learn/mcp-model-context-protocol", "/learn/model-context-protocol"],
  // Pre-existing canonicalSlug markers (already canonical-tagged their
  // winner; now 308-redirect for the same consolidation):
  ["/automate/jira-asana", "/automate/asana-jira"],
  ["/automate/jira-google-calendar", "/automate/google-calendar-jira"],
  ["/automate/linear-jira", "/automate/jira-linear"],
  ["/automate/linear-notion", "/automate/notion-linear"],
  ["/automate/notion-zoom", "/automate/zoom-notion"],
  ["/automate/todoist-slack", "/automate/slack-todoist"],
  ["/learn/embedding", "/learn/embeddings"],
  ["/learn/vector-embeddings", "/learn/embeddings"],
  ["/learn/large-language-model", "/learn/llm"],
  // /automate reverse-order combos, wave-2 extension (alphabetical canonical):
  ["/automate/drive-asana", "/automate/asana-drive"],
  ["/automate/figma-asana", "/automate/asana-figma"],
  ["/automate/github-asana", "/automate/asana-github"],
  ["/automate/google-calendar-airtable", "/automate/airtable-google-calendar"],
  ["/automate/google-calendar-discord", "/automate/discord-google-calendar"],
  ["/automate/hubspot-gmail", "/automate/gmail-hubspot"],
  ["/automate/hubspot-google-calendar", "/automate/google-calendar-hubspot"],
  ["/automate/jira-discord", "/automate/discord-jira"],
  ["/automate/jira-github", "/automate/github-jira"],
  ["/automate/linear-asana", "/automate/asana-linear"],
  ["/automate/linear-github", "/automate/github-linear"],
  ["/automate/linear-hubspot", "/automate/hubspot-linear"],
  ["/automate/notion-airtable", "/automate/airtable-notion"],
  ["/automate/notion-asana", "/automate/asana-notion"],
  ["/automate/notion-drive", "/automate/drive-notion"],
  ["/automate/notion-figma", "/automate/figma-notion"],
  ["/automate/notion-github", "/automate/github-notion"],
  ["/automate/notion-hubspot", "/automate/hubspot-notion"],
  ["/automate/notion-jira", "/automate/jira-notion"],
  ["/automate/salesforce-asana", "/automate/asana-salesforce"],
  ["/automate/salesforce-gmail", "/automate/gmail-salesforce"],
  ["/automate/salesforce-google-calendar", "/automate/google-calendar-salesforce"],
  ["/automate/salesforce-notion", "/automate/notion-salesforce"],
  ["/automate/slack-airtable", "/automate/airtable-slack"],
  ["/automate/slack-discord", "/automate/discord-slack"],
  ["/automate/slack-drive", "/automate/drive-slack"],
  ["/automate/slack-figma", "/automate/figma-slack"],
  ["/automate/slack-hubspot", "/automate/hubspot-slack"],
  ["/automate/slack-salesforce", "/automate/salesforce-slack"],
  ["/automate/stripe-notion", "/automate/notion-stripe"],
  ["/automate/stripe-slack", "/automate/slack-stripe"],
  ["/automate/teams-github", "/automate/github-teams"],
  ["/automate/teams-google-calendar", "/automate/google-calendar-teams"],
  ["/automate/teams-notion", "/automate/notion-teams"],
  ["/automate/todoist-discord", "/automate/discord-todoist"],
  ["/automate/todoist-github", "/automate/github-todoist"],
  ["/automate/todoist-jira", "/automate/jira-todoist"],
  ["/automate/todoist-linear", "/automate/linear-todoist"],
  ["/automate/todoist-notion", "/automate/notion-todoist"],
  ["/automate/trello-discord", "/automate/discord-trello"],
  ["/automate/trello-drive", "/automate/drive-trello"],
  ["/automate/trello-github", "/automate/github-trello"],
  ["/automate/trello-google-calendar", "/automate/google-calendar-trello"],
  ["/automate/trello-slack", "/automate/slack-trello"],
  ["/automate/zoom-asana", "/automate/asana-zoom"],
  ["/automate/zoom-google-calendar", "/automate/google-calendar-zoom"],
  ["/automate/zoom-hubspot", "/automate/hubspot-zoom"],
  ["/automate/zoom-jira", "/automate/jira-zoom"],
  ["/automate/zoom-linear", "/automate/linear-zoom"],
  ["/automate/zoom-slack", "/automate/slack-zoom"],
  ["/automate/zoom-todoist", "/automate/todoist-zoom"],
];

const NON_DEFAULT_LOCALE_PREFIXES = ["/de", "/es", "/fr", "/ja", "/ko", "/pt-BR"];

/**
 * Expand pairs to Next's redirects() entries: one unprefixed row plus one per
 * non-default locale prefix, so a localized request keeps its locale
 * (e.g. /pt-BR/automate/teams-slack → /pt-BR/automate/slack-teams).
 * Permanent = 308.
 */
export function expandCanonicalRedirects(pairs = CANONICAL_REDIRECT_PAIRS) {
  return pairs.flatMap(([from, to]) => [
    { source: from, destination: to, permanent: true },
    ...NON_DEFAULT_LOCALE_PREFIXES.map((localePrefix) => ({
      source: `${localePrefix}${from}`,
      destination: `${localePrefix}${to}`,
      permanent: true,
    })),
  ]);
}

/**
 * The root-relative pairs themselves — also consumed by tests to prove the
 * table matches the `canonicalSlug`/`canonicalPath` JSON markers.
 */
export { CANONICAL_REDIRECT_PAIRS };
