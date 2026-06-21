"use client";

import { CheckmarkCircleIcon } from "@icons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";

interface IntegrationUseCasesProps {
  readonly integration: PublicIntegrationResponse;
}

// Category-to-generic-use-cases map for fallback when no tools are available
const CATEGORY_USE_CASES: Record<string, string[]> = {
  communication: [
    "Send and receive messages through your AI assistant",
    "Get notified about important conversations automatically",
    "Summarize long message threads on demand",
    "Draft and schedule messages using natural language",
    "Automate replies based on custom rules you define",
  ],
  productivity: [
    "Create and manage tasks by just describing them in plain English",
    "Get daily briefings summarizing your to-do list",
    "Automate recurring task creation and assignment",
    "Track progress across projects without switching apps",
    "Set smart reminders that trigger based on context",
  ],
  "project-management": [
    "Create and assign issues from email or chat in one step",
    "Summarize sprint progress and blockers automatically",
    "Move cards across board columns using plain-English commands",
    "Generate weekly status reports from live project data",
    "Get proactive alerts when deadlines are approaching",
  ],
  calendar: [
    "Schedule meetings by describing your availability in plain English",
    "Get a daily briefing of upcoming events every morning",
    "Create recurring events with a single natural-language instruction",
    "Reschedule conflicts automatically based on priority",
    "Invite attendees and generate Google Meet links hands-free",
  ],
  crm: [
    "Log calls and emails to contacts automatically",
    "Pull pipeline summaries without leaving your chat",
    "Create deals and contacts from inbound emails",
    "Get proactive follow-up reminders for cold leads",
    "Generate personalised outreach drafts from CRM data",
  ],
  development: [
    "Create issues and PRs using plain-English descriptions",
    "Get notified about CI failures and review requests instantly",
    "Summarize open pull requests across all repositories",
    "Automate release notes from merged PR descriptions",
    "Query code and commit history through natural language",
  ],
  storage: [
    "Upload and organise files through your AI assistant",
    "Search file contents using natural-language queries",
    "Share links and set permissions with a simple instruction",
    "Summarize documents without downloading them",
    "Trigger workflows when new files are added to a folder",
  ],
  marketing: [
    "Draft campaign copy and social posts on demand",
    "Analyse performance metrics with plain-English queries",
    "Schedule and publish content across channels automatically",
    "Generate audience segments based on engagement data",
    "Get weekly marketing summary reports delivered to you",
  ],
  finance: [
    "Query account balances and transaction history in chat",
    "Automate invoice creation from project data",
    "Get spending summaries and budget alerts proactively",
    "Reconcile expenses without manual data entry",
    "Schedule recurring payments using natural language",
  ],
  analytics: [
    "Ask questions about your data in plain English",
    "Receive scheduled performance reports automatically",
    "Set up anomaly alerts without writing any queries",
    "Share live data snapshots directly in chat",
    "Combine data from multiple sources into one summary",
  ],
};

const FALLBACK_USE_CASES = [
  "Automate repetitive tasks through natural language commands",
  "Get proactive summaries and status updates delivered to you",
  "Connect your workflow to 50+ other tools in the GAIA marketplace",
  "Trigger actions across tools with a single plain-English instruction",
  "Run background automations 24/7 without manual intervention",
];

/**
 * Generate dynamic use-case bullets.
 * If the integration has tools, derive bullets from tool names.
 * Otherwise fall back to category-based or generic bullets.
 */
function generateUseCases(integration: PublicIntegrationResponse): string[] {
  const { name, category, tools } = integration;

  if (tools && tools.length >= 3) {
    // Derive up to 5 capabilities directly from tool names
    return tools.slice(0, 5).map((tool) => {
      const humanName = tool.name
        .replaceAll("_", " ")
        .replaceAll("-", " ")
        .toLowerCase();
      return `Use GAIA to ${humanName} in ${name} with a plain-English instruction`;
    });
  }

  const categoryKey = category.toLowerCase().replaceAll(" ", "-");
  return (
    CATEGORY_USE_CASES[categoryKey] ??
    CATEGORY_USE_CASES[category.toLowerCase()] ??
    FALLBACK_USE_CASES
  ).slice(0, 5);
}

export function IntegrationUseCases({ integration }: IntegrationUseCasesProps) {
  const { name } = integration;
  const useCases =
    integration.content?.useCases && integration.content.useCases.length > 0
      ? integration.content.useCases
      : generateUseCases(integration);

  return (
    <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-medium text-foreground mb-2">
          What you can do with GAIA + {name}
        </h2>
        <p className="text-zinc-400 text-sm leading-relaxed">
          GAIA connects to {name} via MCP (Model Context Protocol) and exposes
          every action as a natural-language command. Tell GAIA what you want
          and it handles the rest, automatically.
        </p>
      </div>
      <ul className="space-y-3">
        {useCases.map((useCase) => (
          <li
            key={useCase}
            className="flex items-start gap-3 text-zinc-300 text-sm"
          >
            <CheckmarkCircleIcon
              className="mt-0.5 flex-shrink-0 h-5 w-5 text-[#00bbff]"
              aria-hidden="true"
            />
            {useCase}
          </li>
        ))}
      </ul>
    </section>
  );
}
