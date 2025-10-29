import type { Metadata } from "next";

import PricingPage from "@/features/pricing/components/PricingPage";
import { generatePageMetadata, generateProductSchema } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Pricing",
  description:
    "Compare GAIA's pricing plans and find the best AI assistant plan for your needs. Choose between free, monthly, and yearly subscriptions. Transparent pricing for every productivity level.",
  path: "/pricing",
  keywords: [
    "GAIA Pricing",
    "AI Assistant Pricing",
    "Subscription Plans",
    "Monthly Plan",
    "Yearly Plan",
    "Free AI Assistant",
    "Pricing Comparison",
    "Affordable AI",
  ],
});

export default function Pricing() {
  const productSchema = generateProductSchema();

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(productSchema) }}
      />
      <PricingPage />
    </>
  );
}
