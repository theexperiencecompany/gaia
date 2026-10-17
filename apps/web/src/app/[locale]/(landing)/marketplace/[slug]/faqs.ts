import type {
  IntegrationContent,
  PublicIntegrationResponse,
} from "@/features/integrations/types";

export interface IntegrationFaq {
  question: string;
  answer: string;
}

type IntegrationFaqSource = Pick<
  PublicIntegrationResponse,
  "name" | "toolCount" | "category"
> & {
  content?: IntegrationContent | null;
  tools?: Array<{ name: string; description?: string | null }>;
  authType?: string | null;
};

/**
 * Visible FAQs for an integration detail page: backend-authored content
 * first, generated fallback otherwise.
 *
 * Consumed by BOTH the visible accordion (IntegrationRichContent) and the
 * FAQPage JSON-LD schema (page.tsx) so the rich snippet never drifts from
 * what visitors actually see.
 */
export function getIntegrationFAQs(
  integration: IntegrationFaqSource,
): IntegrationFaq[] {
  if (integration.content?.faqs && integration.content.faqs.length > 0) {
    return integration.content.faqs;
  }
  return generateIntegrationFAQs(integration);
}

/** "send_message" -> "send message" for readable capability copy. */
function humanizeToolName(toolName: string): string {
  return toolName.replaceAll("_", " ").replaceAll("-", " ").toLowerCase();
}

function connectAnswer(
  name: string,
  authType: string | null | undefined,
): string {
  const intro = `Connecting ${name} to GAIA takes under two minutes. Open the GAIA Marketplace, find the ${name} integration, and click "Add to your GAIA".`;
  if (authType === "oauth") {
    return `${intro} You will be redirected to an OAuth consent screen to approve access. Once authorised, GAIA can immediately use all ${name} tools and you can start automating straight away.`;
  }
  if (authType === "bearer") {
    return `${intro} You will be asked to paste an API token to authorise access. Once authorised, GAIA can immediately use all ${name} tools and you can start automating straight away.`;
  }
  return `${intro} Depending on the integration type, you will either be redirected to an OAuth consent screen or asked to paste a bearer token. Once authorised, GAIA immediately gains access to all ${name} tools and you can start automating straight away.`;
}

function capabilityAnswer(
  name: string,
  toolCount: number,
  categoryLabel: string,
  tools: Array<{ name: string; description?: string | null }> | undefined,
): string {
  const usableTools = (tools ?? []).filter((t) => t.name.trim().length > 0);
  if (usableTools.length > 0) {
    const named = usableTools
      .slice(0, 3)
      .map((t) => humanizeToolName(t.name))
      .join(", ");
    const toolSuffix = toolCount === 1 ? "" : "s";
    return `GAIA exposes all ${toolCount} ${name} tool${toolSuffix} to its AI agent, including ${named}, so you can run any of them by describing it in plain English. GAIA can also combine ${name} with your other connected integrations, for example summarising ${name} data in a scheduled daily briefing.`;
  }
  const toolSuffix = toolCount === 1 ? "" : "s";
  const toolsDescription =
    toolCount > 0
      ? `all ${toolCount} ${name} tool${toolSuffix}`
      : `the available ${name} tools`;
  return `GAIA exposes ${toolsDescription} to its AI agent, meaning you can perform any ${categoryLabel.toLowerCase()} action supported by ${name} just by describing it in plain English. GAIA can also combine ${name} with other connected integrations, for example, triggering a ${name} action whenever a specific email arrives, or summarising ${name} data in a scheduled daily briefing.`;
}

interface CategoryFaq {
  question: (name: string) => string;
  answer: (name: string) => string;
}

/** Per-category Q&A. Answers apply GAIA's agent abilities to available actions only. */
const CATEGORY_FAQS: Record<string, CategoryFaq> = {
  productivity: {
    question: (name) =>
      `How does GAIA turn my ${name} workspace into a daily briefing?`,
    answer: (name) =>
      `GAIA reads your ${name} tasks using its available actions, then summarises what is due, overdue, and upcoming in a morning briefing delivered to chat. Ask follow-ups like "what should I tackle first?" and GAIA answers from live ${name} data.`,
  },
  communication: {
    question: (name) =>
      `Will GAIA watch my ${name} channels and only ping me about urgent threads?`,
    answer: (name) =>
      `Yes. GAIA monitors your ${name} channels using its available actions, summarises long threads on demand, and surfaces messages that need your attention. You describe what counts as urgent in plain English, and GAIA applies that filter going forward.`,
  },
  developer: {
    question: (name) =>
      `Can GAIA triage ${name} issues and prepare summaries for review?`,
    answer: (name) =>
      `Yes. GAIA reads ${name} issues and pull requests through its available actions, summarises the changes and discussion for reviewers, and can file new issues from an email thread or chat message. Test and build failures can be pushed to your team channel with the failing step attached.`,
  },
  development: {
    question: (name) =>
      `Can GAIA triage ${name} issues and prepare summaries for review?`,
    answer: (name) =>
      `Yes. GAIA reads ${name} issues and pull requests through its available actions, summarises the changes and discussion for reviewers, and can file new issues from an email thread or chat message. Test and build failures can be pushed to your team channel with the failing step attached.`,
  },
  analytics: {
    question: (name) =>
      `Can GAIA send me scheduled ${name} reports without me writing queries?`,
    answer: (name) =>
      `Yes. Ask GAIA a question about your ${name} data once in plain English, then ask for it as a daily or weekly report. GAIA re-runs it on schedule using the available ${name} actions and flags anomalies for you.`,
  },
  finance: {
    question: (name) =>
      `Can GAIA track ${name} activity and remind me about money matters?`,
    answer: (name) =>
      `Yes. GAIA pulls balances and recent activity through the available ${name} actions, summarises spending in plain English, and creates follow-up tasks for invoices or unusual transactions.`,
  },
  "ai-ml": {
    question: (name) =>
      `How do I call ${name} models inside my GAIA workflows?`,
    answer: (name) =>
      `Once ${name} is connected, its available actions appear as tools GAIA can call mid-workflow. Ask GAIA to summarise a document, draft copy, or analyse data with ${name}, then pipe the result into email, chat, or docs.`,
  },
  education: {
    question: (name) =>
      `Can GAIA quiz me on ${name} material and keep me on a study schedule?`,
    answer: (name) =>
      `Yes. GAIA reads your ${name} lessons through its available actions, generates practice questions from them, and schedules review reminders. Tell GAIA your exam date and it plans reviews backwards from it.`,
  },
  personal: {
    question: (name) =>
      `Can GAIA run repeating ${name} routines without me asking each time?`,
    answer: (name) =>
      `Yes. Describe the routine once in plain English, for example a morning briefing or a weekly tidy-up, and GAIA runs it on schedule using the available ${name} actions, reporting back in chat.`,
  },
  capabilities: {
    question: (name) => `What system actions can GAIA take through ${name}?`,
    answer: (name) =>
      `GAIA exposes every available ${name} action as a plain-English command and can chain them with your email, calendar, and tasks. Open the tool list on this page to see exactly what is supported.`,
  },
  other: {
    question: (name) =>
      `What can I automate between ${name} and my other tools?`,
    answer: (name) =>
      `Anything the available ${name} actions support, combined with your other connected integrations. A typical setup syncs ${name} with email and chat: new ${name} activity triggers a message, and chat commands read or update ${name}.`,
  },
  calendar: {
    question: (name) =>
      `Can GAIA schedule on my ${name} calendar and brief me before meetings?`,
    answer: (name) =>
      `Yes. GAIA finds free slots, books meetings, and sends a morning briefing of the day ahead using the available ${name} actions. Ask it to resolve conflicts by priority and it rearranges lower-priority events for you.`,
  },
  crm: {
    question: (name) =>
      `Will GAIA keep my ${name} records updated from my inbox?`,
    answer: (name) =>
      `Yes. GAIA logs calls, updates ${name} deals and contacts, and drafts follow-ups from email threads and meeting notes, using the available ${name} actions. Your pipeline stays current with no manual entry.`,
  },
  notes: {
    question: (name) => `How does GAIA save meeting notes to ${name}?`,
    answer: (name) =>
      `GAIA writes meeting summaries, email digests, and task context directly to ${name} through its available actions, building a searchable history with no copy-paste. Ask GAIA to find an old note and it searches ${name} for you.`,
  },
  storage: {
    question: (name) => `Can GAIA find and summarise files in my ${name}?`,
    answer: (name) =>
      `Yes. GAIA searches your ${name} files with plain-English queries, summarises documents without you downloading them, and organises new uploads into the right folders using the available ${name} actions.`,
  },
  marketing: {
    question: (name) =>
      `Can GAIA draft ${name} campaigns and report on performance?`,
    answer: (name) =>
      `Yes. GAIA drafts campaign copy and posts with the available ${name} actions, then answers performance questions in plain English and delivers scheduled summary reports to chat.`,
  },
  email: {
    question: (name) =>
      `Will GAIA triage my ${name} inbox and draft replies for me?`,
    answer: (name) =>
      `Yes. GAIA reads and labels your ${name} inbox using its available actions, drafts replies in your voice for approval, and turns actionable emails into tasks. Tell GAIA which senders matter most and it prioritises around them.`,
  },
  task: {
    question: (name) =>
      `How does GAIA turn emails and chats into ${name} tasks?`,
    answer: (name) =>
      `Forward the outcome you want in plain English, for example "make the website feedback an urgent ${name} task", and GAIA creates it with the right priority and context using the available ${name} actions. It can also summarise your list every morning.`,
  },
  tasks: {
    question: (name) =>
      `How does GAIA turn emails and chats into ${name} tasks?`,
    answer: (name) =>
      `Forward the outcome you want in plain English, for example "make the website feedback an urgent ${name} task", and GAIA creates it with the right priority and context using the available ${name} actions. It can also summarise your list every morning.`,
  },
  automation: {
    question: (name) => `What do I describe when automating ${name} with GAIA?`,
    answer: (name) =>
      `The outcome in plain English, for example "every morning, summarise my ${name} activity and message me the highlights". GAIA maps that to the available ${name} actions and runs it on schedule, reporting back in chat.`,
  },
};

function generateIntegrationFAQs(
  integration: Pick<
    PublicIntegrationResponse,
    "name" | "toolCount" | "category"
  > & {
    tools?: Array<{ name: string; description?: string | null }>;
    authType?: string | null;
  },
): IntegrationFaq[] {
  const { name, toolCount, category, tools, authType } = integration;
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);
  const categoryKey = category.toLowerCase();
  const categoryFaq = CATEGORY_FAQS[categoryKey] ?? CATEGORY_FAQS.other;

  return [
    {
      question: `How do I connect ${name} to GAIA?`,
      answer: connectAnswer(name, authType),
    },
    {
      question: `What can GAIA do with ${name}?`,
      answer: capabilityAnswer(name, toolCount, categoryLabel, tools),
    },
    {
      question: categoryFaq.question(name),
      answer: categoryFaq.answer(name),
    },
    {
      question: `Is the ${name} integration free?`,
      answer: `Community integrations like ${name} are included with every GAIA plan at no extra charge — connect it, run automations, and use all available tools as part of your subscription. Paid plans unlock higher usage limits, priority processing, and advanced workflow features. Visit the GAIA pricing page for full details.`,
    },
  ];
}
