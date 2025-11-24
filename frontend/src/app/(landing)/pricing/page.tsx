import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import type { Plan } from "@/features/pricing/api/pricingApi";
import PricingPage from "@/features/pricing/components/PricingPage";
import { getPlansServer } from "@/features/pricing/lib/serverPricingApi";
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

export const revalidate = 86400; // Revalidate every 24 hours (ISR)

export default async function Pricing() {
  const productSchema = generateProductSchema();

  // Fetch plans data server-side for SSR + ISR
  let initialPlans: Plan[] = [];
  try {
    initialPlans = await getPlansServer();
  } catch (error) {
    console.error("Failed to fetch plans server-side:", error);
    // Component will fallback to client-side fetching
  }

  return (
    <>
      <JsonLd data={productSchema} />
      <PricingPage initialPlans={initialPlans} />
    </>
  );
}
