/**
 * Recovery links rendered by the 404 page (src/app/not-found.tsx).
 *
 * Nonexistent paths return a real HTTP 404, so these anchors are the only
 * recovery surface for crawlers/agents that land on a dead URL — they must
 * stay plain server-rendered links pointing at real destinations.
 *
 * Keep this set short (~5): it is a recovery hint block, not a sitemap
 * dump. /llms.txt already exposes a full machine-readable page index.
 */
export const NOT_FOUND_LINKS = [
  {
    name: "Home",
    href: "/",
    description: "Start over from the GAIA homepage",
  },
  {
    name: "Documentation",
    href: "https://docs.heygaia.io",
    description: "Setup guides, integrations, and release notes",
  },
  {
    name: "Pricing",
    href: "/pricing",
    description: "Plans, features, and limits of every tier",
  },
  {
    name: "llms.txt",
    href: "/llms.txt",
    description: "Machine-readable index of every public page",
  },
  {
    name: "Sitemap",
    href: "/sitemap/0.xml",
    description: "XML sitemap of all static marketing pages",
  },
] as const;

export type NotFoundLink = (typeof NOT_FOUND_LINKS)[number];
