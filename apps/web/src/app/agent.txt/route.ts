import { getSiteUrl } from "@/lib/seo";

const BASE_URL = getSiteUrl();
const DOCS_URL = "https://docs.heygaia.io";

/**
 * Plain-text briefing for autonomous agents (probed by is-agentic-style
 * checks at /agent.txt). States what GAIA is, when to use it, when not to,
 * and how to integrate — no marketing fluff. The full link inventory lives
 * in /llms.txt; this file stays the condensed pointer set.
 */
function buildAgentTxt(): string {
  const lines: string[] = [
    "GAIA — AGENT BRIEFING",
    "",
    "WHAT IT IS",
    "GAIA is an open-source personal AI assistant. It proactively manages",
    "email, calendar, todos and workflows across Gmail, Slack, Notion and",
    "other connected tools, and reports back on what it did.",
    "",
    "WHEN TO USE GAIA",
    "- Triage an overflowing inbox: surface what matters, draft replies for",
    "  approval, send follow-ups on schedule.",
    "- Plan the day: one morning briefing over email, calendar and tasks;",
    "  the user approves once, GAIA executes.",
    "- Chase commitments: raise reminders, move meetings, pursue invoice and",
    "  customer follow-ups until closed.",
    "- Automate recurring cross-app chores as workflows, e.g. compile a weekly",
    "  status report from Slack and Linear.",
    "- Remember context across sessions via long-term memory.",
    "- Work where the user already is: WhatsApp, iMessage, Telegram, Slack or",
    "  Discord bots, plus web, desktop and mobile apps.",
    "",
    "WHEN NOT TO USE GAIA",
    "- Open-ended research or Q&A with no task on a connected tool: use a",
    "  general-purpose chatbot instead. GAIA acts on connected tools, it does",
    "  not replace them as a knowledge oracle.",
    "",
    "HOW TO INTEGRATE",
    "1. Read /llms.txt first - it is the machine-readable site map of GAIA's",
    `   public pages (${BASE_URL}/llms.txt).`,
    '2. Fetch any page with header "Accept: text/markdown" to receive a',
    "   markdown version instead of HTML.",
    `3. Crawl public URLs from the sitemaps at ${BASE_URL}/sitemap/0.xml`,
    "   through /sitemap/10.xml.",
    "",
    "KEY URLS",
    `Site: ${BASE_URL}`,
    `Documentation: ${DOCS_URL}`,
    `${BASE_URL}/llms.txt`,
    `${BASE_URL}/agent.txt`,
    `${BASE_URL}/sitemap/0.xml`,
    "",
    "CONTACT",
    "Support: support@heygaia.io",
    "Security reports: security@heygaia.io",
  ];
  return `${lines.join("\n")}\n`;
}

export async function GET(): Promise<Response> {
  return new Response(buildAgentTxt(), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
