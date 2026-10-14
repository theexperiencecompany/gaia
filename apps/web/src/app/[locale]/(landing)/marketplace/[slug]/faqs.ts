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

function generateIntegrationFAQs(
  integration: Pick<
    PublicIntegrationResponse,
    "name" | "toolCount" | "category"
  >,
): IntegrationFaq[] {
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
      answer: `Community integrations like ${name} are included with every GAIA plan at no extra charge — connect it, run automations, and use all available tools as part of your subscription. Paid plans unlock higher usage limits, priority processing, and advanced workflow features. Visit the GAIA pricing page for full details.`,
    },
    {
      question: `What can GAIA do with ${name}?`,
      answer: `GAIA exposes ${toolsDescription} to its AI agent, meaning you can perform any ${categoryLabel.toLowerCase()} action supported by ${name} just by describing it in plain English. GAIA can also combine ${name} with other connected integrations, for example, triggering a ${name} action whenever a specific email arrives, or summarising ${name} data in a scheduled daily briefing.`,
    },
    {
      question: `Does GAIA's ${name} integration work on mobile?`,
      answer: `Absolutely. GAIA runs on web, desktop (macOS and Windows), and mobile (iOS and Android). Your ${name} integration is available across all platforms with your account, so you can trigger automations, check statuses, and manage your ${categoryLabel.toLowerCase()} workflows from any device, any time.`,
    },
  ];
}
