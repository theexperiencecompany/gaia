"use client";

import {
  ArrowRightIcon,
  CheckmarkCircleIcon,
} from "@theexperiencecompany/gaia-icons/stroke-rounded";
import Link from "next/link";
import FAQAccordion from "@/components/seo/FAQAccordion";
import type { PublicIntegrationResponse } from "@/features/integrations/types";

interface IntegrationRichContentProps {
  readonly integration: PublicIntegrationResponse;
  readonly comparisonSlug?: string;
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

function generateFAQs(
  integration: PublicIntegrationResponse,
): Array<{ question: string; answer: string }> {
  const { name, toolCount, category } = integration;
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);

  const toolSuffix = toolCount === 1 ? "" : "s";
  const toolsDescription =
    toolCount > 0
      ? `all ${toolCount} ${name} tool${toolSuffix}`
      : `the available ${name} tools`;

  return [
    {
      question: `How do I connect ${name} to GAIA?`,
      answer: `Connecting ${name} to GAIA takes under two minutes. Open the GAIA Marketplace, find the ${name} integration, and click "Add to your GAIA". Depending on the integration type, you will either be redirected to an OAuth consent screen or asked to paste a bearer token. Once authorised, GAIA immediately gains access to all ${name} tools and you can start automating straight away.`,
    },
    {
      question: `Is the ${name} integration free?`,
      answer: `Yes. GAIA offers a generous free tier that includes access to community integrations like ${name}. You can connect ${name}, run automations, and use all available tools at no cost. Paid plans unlock higher usage limits, priority processing, and advanced workflow features. Visit the GAIA pricing page for full details.`,
    },
    {
      question: `What can GAIA do with ${name}?`,
      answer: `GAIA exposes ${toolsDescription} to its AI agent, meaning you can perform any ${categoryLabel.toLowerCase()} action supported by ${name} just by describing it in plain English. GAIA can also combine ${name} with other connected integrations — for example, triggering a ${name} action whenever a specific email arrives, or summarising ${name} data in a scheduled daily briefing.`,
    },
    {
      question: `Does GAIA's ${name} integration work on mobile?`,
      answer: `Absolutely. GAIA runs on web, desktop (macOS and Windows), and mobile (iOS and Android). Your ${name} integration is available across all platforms with your account, so you can trigger automations, check statuses, and manage your ${categoryLabel.toLowerCase()} workflows from any device, any time.`,
    },
  ];
}

export function IntegrationRichContent({
  integration,
  comparisonSlug,
}: IntegrationRichContentProps) {
  const useCases = generateUseCases(integration);
  const faqs = generateFAQs(integration);
  const { name, category } = integration;
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);

  return (
    <div className="space-y-12 mt-4">
      {/* Section 1: What you can do */}
      <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-6">
        <div>
          <h2 className="text-2xl font-medium text-foreground mb-2">
            What you can do with GAIA + {name}
          </h2>
          <p className="text-zinc-400 text-sm leading-relaxed">
            GAIA connects to {name} via MCP (Model Context Protocol) and exposes
            every action as a natural-language command. Tell GAIA what you want
            — it handles the rest, automatically.
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

      {/* Section 2: How it works */}
      <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-6">
        <div>
          <h2 className="text-2xl font-medium text-foreground mb-2">
            How it works
          </h2>
          <p className="text-zinc-400 text-sm leading-relaxed">
            Set up your {name} automation in three simple steps — no code
            required.
          </p>
        </div>
        <ol className="space-y-4">
          {[
            {
              step: "1",
              title: `Connect ${name} to GAIA`,
              body: `Open the GAIA Marketplace, find the ${name} integration, and click "Add to your GAIA". Authorise access in under two minutes — no code, no configuration files.`,
            },
            {
              step: "2",
              title: "Tell GAIA what to automate in plain English",
              body: `Describe the task in your own words: "summarise my ${name} activity every morning" or "notify me on Slack when a new ${categoryLabel.toLowerCase()} event happens". GAIA understands context and intent.`,
            },
            {
              step: "3",
              title: "GAIA handles it automatically, 24/7",
              body: `GAIA runs your ${name} automations in the background around the clock. No manual triggers, no scripts to maintain — just results delivered to you.`,
            },
          ].map(({ step, title, body }) => (
            <li key={step} className="flex gap-5">
              <div className="flex-shrink-0 flex items-start pt-0.5">
                <span className="h-8 w-8 rounded-full bg-[#00bbff]/10 border border-[#00bbff]/30 flex items-center justify-center text-[#00bbff] text-sm font-semibold">
                  {step}
                </span>
              </div>
              <div>
                <p className="text-zinc-200 font-medium text-sm mb-1">
                  {title}
                </p>
                <p className="text-zinc-400 text-sm leading-relaxed">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Section 3: FAQ */}
      <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-4">
        <div>
          <h2 className="text-2xl font-medium text-foreground mb-2">
            Frequently asked questions
          </h2>
          <p className="text-zinc-400 text-sm leading-relaxed">
            Everything you need to know about the GAIA {name} integration.
          </p>
        </div>
        <FAQAccordion faqs={faqs} />
      </section>

      {/* Section 4: Related integrations CTA */}
      <section className="rounded-3xl bg-gradient-to-br from-zinc-900/70 to-zinc-900/40 backdrop-blur-md border border-zinc-800/50 p-8 space-y-4">
        <h2 className="text-2xl font-medium text-foreground">
          GAIA connects {name} with your entire stack
        </h2>
        <p className="text-zinc-400 text-sm leading-relaxed max-w-2xl">
          {name} is just one piece of the puzzle. GAIA integrates with 50+ tools
          across {categoryLabel.toLowerCase()}, communication, productivity, and
          more — letting you build cross-tool automations in plain English
          without writing a single line of code.
        </p>
        <Link
          href="/marketplace"
          className="inline-flex items-center gap-2 rounded-xl bg-[#00bbff]/10 hover:bg-[#00bbff]/20 border border-[#00bbff]/30 text-[#00bbff] px-5 py-2.5 text-sm font-medium transition-colors"
        >
          Browse all integrations
          <ArrowRightIcon className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </section>

      {/* Cross-link to comparison page when one exists */}
      {comparisonSlug && (
        <p className="text-sm text-zinc-500 border-t border-zinc-800/50 pt-4">
          Evaluating your options?{" "}
          <Link
            href={`/compare/${comparisonSlug}`}
            className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
          >
            Compare GAIA vs {name} &rarr;
          </Link>
        </p>
      )}
    </div>
  );
}
