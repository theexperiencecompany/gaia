import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import FAQPageClient from "@/features/faq/components/FAQPageClient";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getAllFAQs, getFAQSchema } from "@/lib/faq";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Frequently Asked Questions",
  description:
    "Find answers to common questions about GAIA, your personal AI assistant. Learn about features, pricing, privacy, technical requirements, and how GAIA can boost your productivity.",
  path: "/faq",
  keywords: [
    "GAIA FAQ",
    "Frequently Asked Questions",
    "AI Assistant Questions",
    "GAIA Help",
    "Product Information",
    "Common Questions",
    "Support FAQ",
    "AI Assistant Help",
  ],
});

export default function FAQPage() {
  const faqs = getAllFAQs();
  const faqSchema = getFAQSchema();
  const webPageSchema = generateWebPageSchema(
    "Frequently Asked Questions",
    "Find answers to common questions about GAIA, your personal AI assistant.",
    `${siteConfig.url}/faq`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "FAQ", url: `${siteConfig.url}/faq` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "FAQ", url: `${siteConfig.url}/faq` },
  ]);

  return (
    <>
      <JsonLd data={[faqSchema, webPageSchema, breadcrumbSchema]} />
      <FAQPageClient faqs={faqs} />
      <FinalSection />
    </>
  );
}
