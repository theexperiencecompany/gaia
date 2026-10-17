import type { DocsGuideLink } from "./index";

const DOCS_BASE = "https://docs.heygaia.io";

const EMAIL_GUIDE: DocsGuideLink = {
  title: "Managing Email",
  url: `${DOCS_BASE}/guides/managing-email`,
};

const TASKS_GUIDE: DocsGuideLink = {
  title: "Managing Tasks & Todos",
  url: `${DOCS_BASE}/guides/tasks-todos`,
};

const TOOL_GUIDES: Record<string, DocsGuideLink> = {
  gmail: EMAIL_GUIDE,
  slack: {
    title: "Using GAIA in Slack",
    url: `${DOCS_BASE}/guides/slack-bot`,
  },
  discord: {
    title: "Using GAIA on Discord",
    url: `${DOCS_BASE}/guides/discord-bot`,
  },
  "google-calendar": {
    title: "How Does AI Calendar Scheduling Work?",
    url: `${DOCS_BASE}/knowledge/how/ai-calendar-scheduling`,
  },
  notion: TASKS_GUIDE,
  todoist: TASKS_GUIDE,
  asana: TASKS_GUIDE,
  trello: TASKS_GUIDE,
  clickup: TASKS_GUIDE,
  jira: TASKS_GUIDE,
  linear: TASKS_GUIDE,
  github: TASKS_GUIDE,
  airtable: TASKS_GUIDE,
};

const FALLBACK_GUIDE: DocsGuideLink = {
  title: "Building Your First Workflow",
  url: `${DOCS_BASE}/guides/building-workflows`,
};

/** Tool slugs in priority order: at most two guides per combo page. */
const TOOL_PRIORITY = [
  "gmail",
  "slack",
  "discord",
  "google-calendar",
  "notion",
  "todoist",
  "asana",
  "trello",
  "clickup",
  "jira",
  "linear",
  "github",
  "airtable",
];

/**
 * Docs guides for an `/automate/{combo}` page, derived from the combo's tool
 * slugs. Combos built on email, chat, calendar, or task tools link the
 * matching guides; anything else links the workflow-building guide.
 */
export function getAutomateDocsLinks(
  toolASlug: string,
  toolBSlug: string,
): readonly DocsGuideLink[] {
  const matched = TOOL_PRIORITY.filter(
    (tool) => tool === toolASlug || tool === toolBSlug,
  ).map((tool) => TOOL_GUIDES[tool]);
  const unique = [
    ...new Map(matched.map((guide) => [guide.url, guide])).values(),
  ];
  if (unique.length > 0) {
    return unique.slice(0, 2);
  }
  return [FALLBACK_GUIDE];
}
