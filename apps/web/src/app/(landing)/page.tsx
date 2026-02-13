import type { Metadata } from "next";

import LandingPageClient from "@/app/(landing)/client";
import JsonLd from "@/components/seo/JsonLd";
import { homepageFAQs } from "@/lib/page-faqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateOrganizationSchema,
  generatePageMetadata,
  generateWebPageSchema,
  generateWebSiteSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: siteConfig.name,
  path: "/",
  keywords: [
    "personal AI assistant",
    "productivity tool",
    "task automation",
    "email management",
    "meeting scheduler",
    "AI productivity",
    "workflow automation",
    "smart assistant",
    "digital assistant",
    "AI task manager",
  ],
});

export default function LandingPage() {
  const organizationSchema = generateOrganizationSchema();
  const websiteSchema = generateWebSiteSchema();
  const webPageSchema = generateWebPageSchema(
    siteConfig.name,
    siteConfig.description,
    siteConfig.url,
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
  ]);
  const faqSchema = generateFAQSchema(homepageFAQs);

  return (
    <>
      <JsonLd
        data={[
          organizationSchema,
          websiteSchema,
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
        ]}
      />
      <LandingPageClient />
    </>
  );
}
