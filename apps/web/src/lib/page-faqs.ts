import { ADVERTISED_PRO_MONTHLY_PRICE } from "@/features/pricing/advertisedPrice";

import type { FAQItem } from "./faq";

/**
 * Page-specific FAQ data for GEO optimization.
 * Adding FAQ schema to key pages boosts AI search visibility by up to 40%
 * according to Princeton GEO research.
 */

export const pricingFAQs: FAQItem[] = [
  {
    question: "What is included in GAIA's free plan?",
    answer:
      "GAIA's free plan includes core features: email automation, calendar management, task organization, basic workflow automation, and access to community integrations. It is designed to let you experience GAIA's proactive productivity capabilities before upgrading.",
  },
  {
    question: "How does GAIA's pricing compare to competitors?",
    answer: `GAIA Pro starts at $${ADVERTISED_PRO_MONTHLY_PRICE}/month, comparable to ChatGPT Plus ($20/month) and Motion ($19/month). Unlike these tools, GAIA offers a free tier, self-hosting for $0, and combines capabilities that would otherwise require multiple subscriptions (email management, calendar AI, workflow automation, task management).`,
  },
  {
    question: "Can I self-host GAIA for free?",
    answer:
      "Yes. Self-hosting GAIA is completely free with no recurring costs. You maintain full control over your data and infrastructure. The only cost is your own server/hosting. Our Docker-based setup makes deployment straightforward.",
  },
];
