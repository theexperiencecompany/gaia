/**
 * Canonical URL consolidation: the one source of truth for near-duplicate
 * pages. Each [victim, winner] pair 308-redirects (locale-preserving) before
 * the victim renders; victims stay out of their family `_slugs.json`, and
 * internal links resolve through `src/lib/canonicalLinks.ts`.
 *
 * Plain-js on purpose: `next.config.mjs` (Node) imports it and cannot load TS.
 * Locale prefixes mirror `src/i18n/config.ts`, pinned by the vitest.
 */

const CANONICAL_REDIRECT_PAIRS = [
  // Persona pages that also answered at the site root, canonical-tagged to /for/*
  ["/agency-owners", "/for/agency-owners"],
  ["/engineering-managers", "/for/engineering-managers"],
  ["/product-managers", "/for/product-managers"],
  ["/sales-professionals", "/for/sales-professionals"],
  ["/software-developers", "/for/software-developers"],
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

const NON_DEFAULT_LOCALE_PREFIXES = ["/de", "/es", "/fr", "/ja", "/ko", "/pt-br"];

/**
 * Expand pairs to Next's redirects() entries: one unprefixed row plus one per
 * non-default locale prefix, so a localized request keeps its locale
 * (e.g. /pt-br/automate/teams-slack → /pt-br/automate/slack-teams).
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

/** The root-relative pairs, for the link resolver and the contract test. */
export { CANONICAL_REDIRECT_PAIRS };
