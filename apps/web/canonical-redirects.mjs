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
