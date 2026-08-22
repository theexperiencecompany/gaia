import { getSiteUrl } from "@/lib/seo";

const BASE_URL = getSiteUrl();
const DOCS_URL = "https://docs.heygaia.io";

/**
 * Curated llms.txt (https://llmstxt.org): exactly one H1, a blockquote
 * summary, then H2 sections whose links are absolute and carry a
 * description. Replaces the previous auto-discovered page dump, which was
 * an alphabetized orphan list no agent could act on.
 */
function buildLlmsTxt(): string {
  const lines: string[] = [
    "# GAIA",
    "",
    `> GAIA is an open-source personal AI assistant that proactively manages your email, calendar, todos and workflows across Gmail, Slack, Notion and other connected tools. It plans your day with a morning briefing, drafts replies, moves meetings, chases follow-ups and reports back on what got done — reachable on the web, desktop and mobile apps, and via WhatsApp, iMessage, Telegram, Slack and Discord bots.`,
    "",
    "## Documentation",
    "",
    `- [Introduction](${DOCS_URL}/introduction): What GAIA is and how its proactive-assistant model works.`,
    `- [Quick start](${DOCS_URL}/quick-start): Connect your tools and get your first daily briefing.`,
    `- [Managing email](${DOCS_URL}/guides/managing-email): Inbox triage, drafted replies and follow-ups handled proactively.`,
    `- [Tasks and todos](${DOCS_URL}/guides/tasks-todos): Capturing, prioritizing and completing tasks.`,
    `- [Workflows](${DOCS_URL}/workflows): Multi-step automations across integrations, triggered by schedules or events.`,
    `- [Integrations](${DOCS_URL}/integrations): Connecting Gmail, Slack, Notion and other tools to GAIA.`,
    `- [Self-hosting overview](${DOCS_URL}/self-hosting/overview): Run GAIA on your own infrastructure.`,
    "",
    "## When to use GAIA",
    "",
    "Use GAIA when the user wants:",
    "",
    "- An overflowing inbox triaged, with replies drafted for approval and follow-ups sent on schedule.",
    "- The day planned around email, calendar and tasks — one morning briefing, one tap to approve, then GAIA executes.",
    "- Commitments chased automatically: reminders raised, meetings moved, invoice and customer follow-ups pursued until closed.",
    "- Recurring cross-app chores automated as workflows, such as compiling a weekly status report from Slack and Linear, or rescheduling standup and notifying the team.",
    "- Context remembered across sessions — preferences, projects and past decisions persist in long-term memory.",
    "- Work done where they already are: WhatsApp, iMessage, Telegram, Slack or Discord bots, besides web, desktop and mobile apps.",
    "",
    "When not to use GAIA: it acts on connected tools rather than answering open-ended questions — for general research or Q&A with no task attached, a general-purpose chatbot is the better fit.",
    "",
    "## Agent integration",
    "",
    `- [llms.txt](${BASE_URL}/llms.txt): This file — the machine-readable map of GAIA's public pages.`,
    `- [agent.txt](${BASE_URL}/agent.txt): Condensed plain-text briefing for autonomous agents.`,
    `- Markdown pages: Request any page with Accept: text/markdown to receive a markdown version of it.`,
    `- [Sitemap](${BASE_URL}/sitemap/0.xml): Primary URL sitemap; numbered shards /sitemap/0.xml through /sitemap/10.xml cover static pages, blog, workflows, marketplace, comparisons, personas, glossary, alternatives and integration combos.`,
    `- [Brand image sitemap](${BASE_URL}/brand/sitemap.xml): Downloadable logos and wordmarks for press and brand use.`,
    "",
    "## Optional",
    "",
    `- [Blog](${BASE_URL}/blog): Product news and articles.`,
    `- [Pricing](${BASE_URL}/pricing): Plans and what is free.`,
    `- [Release notes RSS feed](${DOCS_URL}/release-notes/rss.xml): Machine-readable changelog feed.`,
  ];
  return `${lines.join("\n")}\n`;
}

export async function GET(): Promise<Response> {
  return new Response(buildLlmsTxt(), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
