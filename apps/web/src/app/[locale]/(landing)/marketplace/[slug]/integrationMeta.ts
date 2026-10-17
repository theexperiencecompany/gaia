const MAX_META_DESCRIPTION_LENGTH = 155;
const MIN_META_DESCRIPTION_LENGTH = 120;

/** Pads sub-120-char descriptions. Matches the FAQ: community integrations ship with every plan. */
const SHORT_DESCRIPTION_PAD = " Connect free with any GAIA plan.";

function fitMetaDescription(base: string, toolsNote: string): string {
  const withTools = `${base}${toolsNote}`;
  if (
    withTools.length >= MIN_META_DESCRIPTION_LENGTH &&
    withTools.length <= MAX_META_DESCRIPTION_LENGTH
  )
    return withTools;
  if (withTools.length < MIN_META_DESCRIPTION_LENGTH) {
    // Short integration name and/or no tools: pad once (119 + 33 = 152 max).
    return `${withTools}${SHORT_DESCRIPTION_PAD}`;
  }
  if (base.length <= MAX_META_DESCRIPTION_LENGTH) return base;
  // Extremely long integration name: trim at a word boundary.
  const trimmed = base.slice(0, MAX_META_DESCRIPTION_LENGTH - 1);
  return `${trimmed.slice(0, trimmed.lastIndexOf(" "))}…`;
}

export function generateIntegrationDescription(integration: {
  name: string;
  category: string;
  description?: string;
  toolCount?: number;
}): string {
  const name = integration.name;
  const toolCount = integration.toolCount || 0;
  const toolsNote = toolCount > 0 ? ` ${toolCount} actions available.` : "";

  // Real browse taxonomy plus legacy labels. Each entry names the
  // integration and frames one category-specific capability.
  const categoryDescriptions: Record<string, string> = {
    productivity: `Connect ${name} to GAIA to create tasks, set reminders, and get a morning briefing in plain English, all without leaving chat.`,
    communication: `Link ${name} with GAIA to summarize long threads, flag urgent messages, and draft replies in plain English, right from chat.`,
    developer: `Pair ${name} with GAIA to triage issues, summarize pull requests, and watch CI status from chat without opening dashboards.`,
    development: `Pair ${name} with GAIA to triage issues, summarize pull requests, and watch CI status from chat without opening dashboards.`,
    analytics: `Ask GAIA about your ${name} data in plain English and get scheduled reports plus anomaly alerts delivered to chat.`,
    finance: `Ask GAIA for ${name} balances, log expenses from chat, and get budget alerts with no manual entry or spreadsheets.`,
    "ai-ml": `Call ${name} models through GAIA in plain English and pipe the results into email, chat, and docs automatically.`,
    education: `Study with ${name} through GAIA: summarize lessons, quiz yourself, and schedule review reminders that keep you on track.`,
    personal: `Let GAIA handle ${name} for you: reminders, summaries, and repeating routines with no manual setup required.`,
    capabilities: `Trigger ${name} actions through GAIA in plain English, combined with your email, calendar, and tasks in one place.`,
    other: `Connect ${name} to GAIA and run its actions with plain-English commands across your whole stack, no code needed.`,
    calendar: `Let GAIA manage your ${name} calendar: schedule meetings, brief you every morning, and fix conflicts in plain English.`,
    crm: `Let GAIA log calls, update ${name} deals, and draft follow-ups from your inbox in plain English, keeping records current.`,
    notes: `Save meeting notes and email summaries to ${name} with GAIA, building a searchable history with no copy-paste needed.`,
    storage: `Ask GAIA to find, summarize, and organize ${name} files with plain-English commands. No downloads needed, ever.`,
    marketing: `Draft ${name} campaign copy with GAIA, review performance in plain English, and schedule posts across channels.`,
    email: `Let GAIA triage your ${name} inbox, draft replies in your voice, and turn emails into tasks in plain English.`,
    task: `Turn emails and chats into ${name} tasks with GAIA, then prioritize and track them all in plain English.`,
    tasks: `Turn emails and chats into ${name} tasks with GAIA, then prioritize and track them all in plain English.`,
    automation: `Describe what to automate in plain English and GAIA will run it across ${name} and your other tools, around the clock.`,
  };

  const categoryKey = integration.category?.toLowerCase();
  const base =
    (categoryKey && categoryDescriptions[categoryKey]) ??
    `Connect ${name} to GAIA and run its actions with plain-English commands across your whole stack, no code needed.`;

  return fitMetaDescription(base, toolsNote);
}

/** Marketplace page slugs whose ranking queries carry per-tool MCP intent. */
const MCP_SERVER_SLUGS: ReadonlySet<string> = new Set([
  "linkup",
  "web-fetch",
  "any-do",
  "hey-email-mcp",
  "wakatime",
  "pixellab",
  "google-meet",
  "sequential-thinking",
]);

export function generateIntegrationTitle(
  name: string,
  category: string,
  slug?: string,
): string {
  // Only slugs whose ranking queries carry "... mcp" intent (GSC) get MCP Server phrasing.
  if (slug && MCP_SERVER_SLUGS.has(slug)) {
    return `${name} MCP Server: Automate with AI`;
  }
  // The layout title template appends "| GAIA" — never include the brand here,
  // and keep titles short enough to survive SERP truncation (~60 chars).
  const categoryTitles: Record<string, string> = {
    email: `${name} AI Email Integration: Auto-Triage & Replies`,
    calendar: `${name} AI Calendar Integration: Smart Scheduling`,
    task: `${name} AI Task Integration: Auto-Create Tasks`,
    tasks: `${name} AI Task Integration: Auto-Create Tasks`,
    communication: `${name} AI Integration: Monitor & Summarize Messages`,
    crm: `${name} AI CRM Integration: Auto-Update Contacts & Deals`,
    development: `${name} AI Integration: Automate Engineering Workflows`,
    notes: `${name} AI Notes Integration: Auto-Save Notes & Summaries`,
  };
  const key = category?.toLowerCase();
  return (
    categoryTitles[key] ?? `${name} AI Integration: Automate ${name} Workflows`
  );
}
