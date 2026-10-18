import { ADVERTISED_PRO_MONTHLY_PRICE } from "@/features/pricing/advertisedPrice";

import type { FAQItem } from "./faq";

/**
 * Page-specific FAQ data for GEO optimization.
 * Adding FAQ schema to key pages boosts AI search visibility by up to 40%
 * according to Princeton GEO research.
 */

export const pricingFAQs: FAQItem[] = [
  {
    question: "What is included in GAIA Pro?",
    answer:
      "GAIA Pro is the one hosted plan: email automation, calendar management, task organization, workflow automation, and integrations with the tools you already use, billed monthly or yearly. There is no free hosted plan; Enterprise adds what larger teams need.",
  },
  {
    question: "How does GAIA's pricing compare to competitors?",
    answer: `GAIA Pro is $${ADVERTISED_PRO_MONTHLY_PRICE}/month, comparable to ChatGPT Plus ($20/month) and Motion ($19/month). Unlike these tools, GAIA can be self-hosted free for non-commercial use, and one plan combines capabilities that would otherwise require multiple subscriptions (email management, calendar AI, workflow automation, task management).`,
  },
  {
    question: "Can I self-host GAIA for free?",
    answer:
      "Yes, for non-commercial use. GAIA is source-available under the PolyForm Noncommercial license, so personal and other non-commercial self-hosting costs nothing beyond your own server and model API usage. Commercial use needs a separate license. Our Docker-based setup makes deployment straightforward.",
  },
];
