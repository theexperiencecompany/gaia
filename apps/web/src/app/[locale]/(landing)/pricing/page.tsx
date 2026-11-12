import type { Metadata } from "next";
import { connection } from "next/server";

import JsonLd from "@/components/seo/JsonLd";
import PricingPage from "@/features/pricing/components/PricingPage";
import { getPlansServer } from "@/features/pricing/lib/serverPricingApi";
import { faqData } from "@/lib/faq";
import { pricingFAQs } from "@/lib/page-faqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA Pricing: Pro Plan, Monthly or Yearly",
  description:
    "Hosted GAIA is one paid Pro plan, billed monthly or yearly, with Enterprise for teams. Self-hosting is free for non-commercial use. See what each includes.",
  path: "/pricing",
  image: "/api/og/pricing",
  keywords: [
    "GAIA Pricing",
    "AI Assistant Pricing",
    "Subscription Plans",
    "Monthly Plan",
    "Yearly Plan",
    "Pricing Comparison",
    "Affordable AI",
  ],
});

export default async function Pricing() {
  // Rendered per request from the cached plan list, so the build never reads the API.
  await connection();
  const productSchema = generateProductSchema();
  const webPageSchema = generateWebPageSchema(
    "Pricing",
    "Compare GAIA's pricing plans and find the best AI assistant plan for your needs.",
    `${siteConfig.url}/pricing`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Pricing", url: `${siteConfig.url}/pricing` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Pricing", url: `${siteConfig.url}/pricing` },
  ]);

  const combinedFaqSchema = generateFAQSchema([...pricingFAQs, ...faqData]);

  const initialPlans = await getPlansServer();

  return (
    <>
      <JsonLd
        data={[
          productSchema,
          webPageSchema,
          breadcrumbSchema,
          combinedFaqSchema,
        ]}
      />
      <PricingPage initialPlans={initialPlans} />
    </>
  );
}
