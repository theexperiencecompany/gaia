import type { DocsGuideLink } from "../index";

const DOCS_BASE = "https://docs.heygaia.io";

const EMAIL_GUIDE: DocsGuideLink = {
  title: "Managing Email",
  url: `${DOCS_BASE}/guides/managing-email`,
};

const TASKS_GUIDE: DocsGuideLink = {
  title: "Managing Tasks & Todos",
  url: `${DOCS_BASE}/guides/tasks-todos`,
};

/**
 * marketplace detail -> docs.heygaia.io cross-links, keyed by the same slug
 * the detail page is served under (native integration id or community slug).
 * Slugs with no entry fall back to getMarketplaceFallbackGuides() below.
 * Templates render entries inside their existing related-links section as
 * server-rendered links. Docs URLs are absolute so they survive locale
 * prefixes.
 */
export const MARKETPLACE_DOCS_LINKS: Record<string, readonly DocsGuideLink[]> =
  {
    gmail: [EMAIL_GUIDE],
    slack: [
      {
        title: "Using GAIA in Slack",
        url: `${DOCS_BASE}/guides/slack-bot`,
      },
    ],
    discord: [
      {
        title: "Using GAIA on Discord",
        url: `${DOCS_BASE}/guides/discord-bot`,
      },
    ],
    googlecalendar: [
      {
        title: "How Does AI Calendar Scheduling Work?",
        url: `${DOCS_BASE}/knowledge/how/ai-calendar-scheduling`,
      },
    ],
    github: [TASKS_GUIDE],
    linear: [TASKS_GUIDE],
    jira: [TASKS_GUIDE],
    notion: [TASKS_GUIDE],
    todoist: [TASKS_GUIDE],
    airtable: [
      {
        title: "Integrations",
        url: `${DOCS_BASE}/integrations`,
      },
    ],
  };

/** Guides for community integrations with no curated entry above. */
export function getMarketplaceFallbackGuides(): readonly DocsGuideLink[] {
  return [
    {
      title: "Adding MCP Integrations",
      url: `${DOCS_BASE}/guides/adding-mcp-integrations`,
    },
    {
      title: "Marketplace",
      url: `${DOCS_BASE}/guides/marketplace`,
    },
  ];
}
